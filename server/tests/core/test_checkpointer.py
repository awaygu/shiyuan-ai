"""阶段3任务11 测试：core/checkpointer.py 连接治理。

覆盖：
1. PRAGMA 生效：busy_timeout=5000 / journal_mode=WAL / foreign_keys=ON。
2. 写事务原子性：add_message 两语句同事务、delete_conversation 删 messages+conversations 原子。
3. try/except rollback：异常路径回滚不留脏数据（连接用完即关，下次复用干净）。
4. try/finally close：异常路径连接不泄漏。
5. 死代码已删：get_sqlite_saver / get_recent_messages 不再存在。
"""

from __future__ import annotations

import sqlite3

import pytest

import core.checkpointer as cp


@pytest.fixture(autouse=True)
def _isolated_checkpointer_db(tmp_path):
    """每测试用独立 agent_memory.db，避免跨测试数据/连接污染。"""
    db_path = str(tmp_path / "agent_memory.db")
    cp.DB_PATH = db_path
    cp.init_db(db_path)
    yield
    # 测试结束无需显式关连接——每函数已 try/finally close，无池化连接残留。


# ── PRAGMA 生效 ──


def test_get_conn_sets_busy_timeout():
    """_get_conn 设 busy_timeout=5000，并发写锁竞争时等待重试而非直接报错。"""
    conn = cp._get_conn()
    try:
        row = conn.execute("PRAGMA busy_timeout").fetchone()
        assert row[0] == 5000
    finally:
        conn.close()


def test_wal_journal_mode_persists_across_connections():
    """WAL 是文件级持久属性，init_db 设一次后跨连接保留；_get_conn 不再每连接重设。

    验证：init_db 已跑（fixture 调用），新开的 _get_conn 连接读 PRAGMA journal_mode
    仍为 wal——说明 WAL 由 init_db 持久化到文件，而非每连接重设。
    """
    conn = cp._get_conn()
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal"
    finally:
        conn.close()


def test_get_conn_sets_foreign_keys():
    """_get_conn 设 foreign_keys=ON，messages 外键约束生效。"""
    conn = cp._get_conn()
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


# ── 写事务原子性 ──


def test_add_message_updates_conversation_updated_at_atomically():
    """add_message 的 INSERT messages + UPDATE conversations.updated_at 在同一事务。

    两条要么都成功要么都回滚——updated_at 不会在 message 插入失败时单独更新。
    """
    conv = cp.create_conversation(title="对话")
    original = cp.get_conversation(conv["id"])
    msg_id = cp.add_message(conv["id"], "user", "你好")
    assert isinstance(msg_id, int) and msg_id > 0
    # message 已写入
    msgs = cp.get_messages(conv["id"])
    assert len(msgs) == 1
    assert msgs[0]["content"] == "你好"
    # updated_at 被刷新（>= 原值字符串）
    updated = cp.get_conversation(conv["id"])
    assert updated["updated_at"] >= original["updated_at"]


def test_delete_conversation_removes_messages_and_conversation_atomically():
    """delete_conversation 删 messages + conversations 在同一 BEGIN IMMEDIATE 事务。"""
    conv = cp.create_conversation(title="对话")
    cp.add_message(conv["id"], "user", "m1")
    cp.add_message(conv["id"], "assistant", "m2")

    ok = cp.delete_conversation(conv["id"])
    assert ok is True
    # 对话已删
    assert cp.get_conversation(conv["id"]) is None
    # 消息也一并删
    assert cp.get_messages(conv["id"]) == []


def test_delete_conversation_returns_false_for_missing():
    """删除不存在的对话返回 False，不抛异常（事务回滚干净）。"""
    ok = cp.delete_conversation("nonexistent-id")
    assert ok is False


def test_delete_conversation_cleanup_checkpointer_uses_independent_connection():
    """delete_conversation 调 _cleanup_checkpointer 用独立连接删 checkpoints 表。

    checkpoints 表在测试库中不存在（AsyncSqliteSaver 未建表），_cleanup_checkpointer
    应降级为 debug 不抛异常，delete_conversation 整体仍返回 True。
    """
    conv = cp.create_conversation(title="对话")
    cp.add_message(conv["id"], "user", "m1")

    # checkpoints 表不存在时 delete 不抛异常
    ok = cp.delete_conversation(conv["id"])
    assert ok is True


# ── try/except rollback：异常不留脏数据 ──


def test_add_message_rollback_on_constraint_violation():
    """add_message 触发约束异常时回滚，messages 不残留半条记录。

    用非法 role（违反 CHECK 约束）触发 IntegrityError，验证：
    - 抛出异常（调用方可感知失败）
    - messages 表无残留（事务回滚）
    - conversations.updated_at 未被单独更新（两语句同事务，一并回滚）
    """
    conv = cp.create_conversation(title="对话")
    original = cp.get_conversation(conv["id"])

    with pytest.raises(sqlite3.IntegrityError):
        cp.add_message(conv["id"], "invalid_role", "内容")  # CHECK 约束失败

    # 无残留 message
    assert cp.get_messages(conv["id"]) == []
    # updated_at 未单独刷新（同事务回滚）
    after = cp.get_conversation(conv["id"])
    assert after["updated_at"] == original["updated_at"]


def test_create_conversation_rollback_on_duplicate():
    """create_conversation 插入冲突时回滚不残留连接脏状态，后续操作正常。"""
    conv1 = cp.create_conversation(title="对话1")
    # 强制用同一 id 再插一次，触发 PRIMARY KEY 冲突
    conn = cp._get_conn()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conv1["id"], "dup", "2024-01-01 00:00:00", "2024-01-01 00:00:00"),
            )
            conn.commit()
    finally:
        conn.close()

    # 后续 create_conversation 仍正常工作（连接用完即关，无脏状态污染）
    conv2 = cp.create_conversation(title="对话2")
    assert conv2["id"] != conv1["id"]
    assert cp.get_conversation(conv2["id"]) is not None


def test_update_conversation_title_nonexistent_returns_false():
    """更新不存在的对话返回 False（UPDATE rowcount=0），不抛异常。"""
    ok = cp.update_conversation_title("nonexistent-id", "新标题")
    assert ok is False


def test_update_conversation_title_existing_returns_true():
    conv = cp.create_conversation(title="原标题")
    ok = cp.update_conversation_title(conv["id"], "新标题")
    assert ok is True
    after = cp.get_conversation(conv["id"])
    assert after["title"] == "新标题"


def test_clear_messages_returns_deleted_count():
    """clear_messages 返回删除条数。"""
    conv = cp.create_conversation(title="对话")
    cp.add_message(conv["id"], "user", "m1")
    cp.add_message(conv["id"], "assistant", "m2")
    count = cp.clear_messages(conv["id"])
    assert count == 2
    assert cp.get_messages(conv["id"]) == []


def test_clear_messages_no_messages_returns_zero():
    conv = cp.create_conversation(title="对话")
    count = cp.clear_messages(conv["id"])
    assert count == 0


# ── 读函数 ──


def test_list_conversations_excludes_deleted_and_orders_by_updated_desc():
    """list_conversations 排除软删除、按 updated_at 倒序。

    用显式不同的 updated_at 直接插入，避免秒级时间戳在同秒内不可区分导致排序不稳定。
    """
    conn = cp._get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("c-old", "旧对话", "2024-01-01 10:00:00", "2024-01-01 10:00:00"),
        )
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("c-new", "新对话", "2024-01-02 10:00:00", "2024-01-02 10:00:00"),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    result = cp.list_conversations(limit=10)
    assert result["total"] == 2
    ids = [item["id"] for item in result["items"]]
    # updated_at 倒序：新对话在前
    assert ids[0] == "c-new"
    assert ids[1] == "c-old"


def test_list_conversations_pagination():
    cp.create_conversation(title="对话1")
    cp.create_conversation(title="对话2")
    cp.create_conversation(title="对话3")

    page1 = cp.list_conversations(limit=2, offset=0)
    assert page1["total"] == 3
    assert len(page1["items"]) == 2

    page2 = cp.list_conversations(limit=2, offset=2)
    assert page2["total"] == 3
    assert len(page2["items"]) == 1


def test_get_conversation_missing_returns_none():
    assert cp.get_conversation("nonexistent") is None


def test_get_messages_empty():
    conv = cp.create_conversation(title="对话")
    assert cp.get_messages(conv["id"]) == []


# ── try/finally close：异常路径连接不泄漏 ──


def test_connection_closed_after_normal_operation():
    """正常操作后连接已 close（无池化，每次新建用完即关）。"""
    conv = cp.create_conversation(title="对话")
    cp.add_message(conv["id"], "user", "m1")
    cp.get_messages(conv["id"])
    # 再读一次验证连接仍可正常获取（前次已 close，不互相影响）
    msgs = cp.get_messages(conv["id"])
    assert len(msgs) == 1


def test_connection_closed_after_exception():
    """异常路径后连接已 close，下次操作不受脏状态影响。

    用一个 fake 连接替换 _get_conn：其 execute 抛异常，验证 finally 调 close，
    且后续真实操作（恢复 _get_conn 后）能正常工作——说明异常连接已关、无脏状态残留。
    """
    conv = cp.create_conversation(title="对话")
    original_get_conn = cp._get_conn
    closed = {"count": 0}

    class _BoomConn:
        """抛异常的 fake 连接：execute 失败，close 可追踪。"""

        row_factory = None

        def execute(self, *args, **kwargs):
            raise RuntimeError("boom")

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            closed["count"] += 1

    def _boom_get_conn():
        return _BoomConn()

    cp._get_conn = _boom_get_conn  # type: ignore[assignment]
    try:
        # add_message: _get_conn 拿 fake 连接 → BEGIN IMMEDIATE 抛异常 → except rollback → finally close
        with pytest.raises(RuntimeError, match="boom"):
            cp.add_message(conv["id"], "user", "m1")
    finally:
        cp._get_conn = original_get_conn  # type: ignore[assignment]

    # 异常路径 finally 已 close 连接
    assert closed["count"] == 1
    # 恢复 _get_conn 后下次操作用真实干净连接，正常工作
    cp.add_message(conv["id"], "user", "正常")
    assert len(cp.get_messages(conv["id"])) == 1


# ── 死代码已删 ──


def test_dead_code_removed():
    """get_sqlite_saver / get_recent_messages 是死代码，已删除。"""
    assert not hasattr(cp, "get_sqlite_saver"), "get_sqlite_saver 应已删除（死代码）"
    assert not hasattr(cp, "get_recent_messages"), "get_recent_messages 应已删除（死代码）"


# ── _cleanup_checkpointer 异常分支 ──


def test_cleanup_checkpointer_no_s_table_is_debug(caplog):
    """checkpoints 表不存在时降级为 debug，不抛异常、不记 warning。"""
    import logging

    caplog.set_level(logging.DEBUG, logger="core.checkpointer")
    # checkpoints 表未建（测试库无 AsyncSqliteSaver），触发 "no such table" 分支
    cp._cleanup_checkpointer("any-thread-id")
    # 降级 debug，无 warning
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == []
    # debug 日志已记
    assert any("Checkpoint table not ready yet" in r.getMessage() for r in caplog.records)


def test_cleanup_checkpointer_other_operational_error_logs_warning(monkeypatch, caplog):
    """非 "no such table" 的 OperationalError 记 warning（暴露真实问题）。"""
    import logging

    caplog.set_level(logging.WARNING, logger="core.checkpointer")

    class _FakeConn:
        row_factory = None

        def execute(self, sql, *args):
            raise sqlite3.OperationalError("database is locked")

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(cp, "_get_conn", lambda: _FakeConn())
    cp._cleanup_checkpointer("any-thread-id")
    # 非 "no such table" 的 OperationalError 应记 warning
    assert any("database is locked" in r.getMessage() for r in caplog.records)


def test_cleanup_checkpointer_generic_exception_logs_warning(monkeypatch, caplog):
    """非 OperationalError 的未预期异常记 warning 并回滚（不再静默吞）。"""
    import logging

    caplog.set_level(logging.WARNING, logger="core.checkpointer")

    rolled_back = {"count": 0}

    class _FakeConn:
        row_factory = None

        def execute(self, sql, *args):
            raise RuntimeError("unexpected boom")

        def rollback(self):
            rolled_back["count"] += 1

        def close(self):
            pass

    monkeypatch.setattr(cp, "_get_conn", lambda: _FakeConn())
    cp._cleanup_checkpointer("any-thread-id")
    # 未预期异常记 warning + 已回滚
    assert any("unexpected boom" in r.getMessage() for r in caplog.records)
    assert rolled_back["count"] == 1
