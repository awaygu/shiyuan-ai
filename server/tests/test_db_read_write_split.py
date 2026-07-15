"""阶段2 任务6 读写分离回归测试。

验证 database.py 的写连接（get_db）与读连接池（get_read_db）分离：
- get_read_db 返回的连接与写连接不同实例（读不阻塞写）。
- 读连接池复用空闲读连接（非每次新建）。
- close_db 同时关闭写连接 + 清空读连接池（跨测试隔离）。
- upsert_news_returning 用 RETURNING 返回真正新增的 news_id 列表。
- transaction 上下文管理器执行 BEGIN IMMEDIATE 并在异常时 rollback。
- 复合写函数（rename_kb_doc / delete_kb_doc / update_kb / delete_kb /
  create_conversation / save_kb_chunks / upsert_news）仍走写连接，SELECT 后的
  UPDATE/DELETE 在同一写连接内完成。

全部离线：真实 SQLite（tmp_path 隔离），无外部网络。
"""

from __future__ import annotations

import pytest

import database as db


def _news(news_id: str, source: str = "cls-hot", published_at: str = "2024-01-01T00:00:00") -> dict:
    return {
        "news_id": news_id,
        "title": f"title-{news_id}",
        "summary": f"summary-{news_id}",
        "content": "",
        "source": source,
        "url": f"https://example.com/{news_id}",
        "published_at": published_at,
        "extra": {"media_type": "article"},
    }


@pytest.fixture(autouse=True)
async def _fresh_db(monkeypatch, tmp_path):
    """每个测试独立 DB + 新写连接 + 空读连接池。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai.db")
    await db.close_db()
    monkeypatch.setattr(db, "_db", None)
    await db.init_db()
    yield
    await db.close_db()


# ── 1. 读写连接分离 ──────────────────────────────────────────────


async def test_get_read_db_returns_distinct_connection_from_write():
    """get_read_db 借出的读连接与 get_db 写连接是不同实例。"""
    write_conn = await db.get_db()
    async with db.get_read_db() as read_conn:
        assert read_conn is not write_conn
    # 写连接不受读连接关闭/归还影响
    assert write_conn is await db.get_db()


async def test_read_pool_reuses_idle_connection():
    """读连接池复用空闲读连接：连续两次读拿到同一连接对象。"""
    async with db.get_read_db() as first:
        first_id = id(first)
    # 归还后再借，池非空时应复用同一连接
    async with db.get_read_db() as second:
        assert id(second) == first_id


async def test_read_pool_grows_to_size_then_blocks_or_creates():
    """并发借出时池会新建读连接（不超过 pool_size）。

    这里通过嵌套 async with 同时持有两个读连接，验证它们是不同实例
    （说明池在空闲池空时新建而非等待复用）。
    """
    async with db.get_read_db() as c1, db.get_read_db() as c2:
        assert c1 is not c2
    # 两连接归还后池有 2 条空闲
    assert db._read_pool is not None
    assert len(db._read_pool) == 2


# ── 2. close_db 清空读连接池（测试隔离） ────────────────────────


async def test_close_db_resets_read_pool(monkeypatch, tmp_path):
    """close_db 关闭并置空读连接池，下次 get_read_db 按新 DB_PATH 重建。"""
    async with db.get_read_db():
        pass  # 借一次让池里有连接
    assert db._read_pool is not None
    assert len(db._read_pool) == 1

    await db.close_db()
    assert db._read_pool is None
    assert db._read_semaphore is None
    assert db._db is None

    # 切到新 DB_PATH，重建后读池应针对新路径
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai2.db")
    await db.init_db()
    async with db.get_read_db() as conn2:
        # 新读连接能正常查询（新库已迁移）
        cursor = await conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in await cursor.fetchall()}
    assert "news" in tables
    await db.close_db()


# ── 3. upsert_news_returning ──────────────────────────────────────


async def test_upsert_news_returning_empty_returns_zero_empty():
    assert await db.upsert_news_returning([]) == (0, [])


async def test_upsert_news_returning_returns_inserted_ids():
    """新增的 id 全部 RETURNING；已存在的 id 不出现。"""
    # 预置一个已存在的
    await db.upsert_news([_news("old")])
    count, ids = await db.upsert_news_returning([_news("old"), _news("new1"), _news("new2")])
    assert count == 2
    assert set(ids) == {"new1", "new2"}
    # old 被 INSERT OR IGNORE 忽略，不出现在返回列表
    assert "old" not in ids


async def test_upsert_news_returning_count_matches_rowcount_semantics():
    """返回的 count 与 upsert_news 的整数返回一致。"""
    items = [_news(f"n{i}") for i in range(3)]
    int_count = await db.upsert_news(items)
    # 第二次全是重复，count 应为 0
    count, ids = await db.upsert_news_returning(items)
    assert int_count == 3
    assert count == 0
    assert ids == []


# ── 4. transaction 上下文管理器 ──────────────────────────────────


async def test_transaction_commits_on_normal_exit():
    """正常退出时 commit，数据持久化。"""
    async with db.transaction() as conn:
        await conn.execute(
            "INSERT INTO news (news_id, title, summary, content, source, url, published_at, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("tx1", "t", "s", "c", "cls-hot", "u", "2024-01-01", "{}"),
        )
    # 事务已提交，读连接可见
    got = await db.get_news("tx1")
    assert got is not None
    assert got["title"] == "t"


async def test_transaction_rolls_back_on_exception():
    """抛异常时 rollback，未提交的写不可见。"""
    with pytest.raises(ValueError, match="boom"):
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT INTO news (news_id, title, summary, content, source, url, published_at, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("rb1", "t", "s", "c", "cls-hot", "u", "2024-01-01", "{}"),
            )
            raise ValueError("boom")
    assert await db.get_news("rb1") is None


async def test_transaction_uses_write_connection():
    """transaction 拿的是写连接（与 get_db 同实例）。"""
    write_conn = await db.get_db()
    async with db.transaction() as conn:
        assert conn is write_conn


# ── 5. 复合写函数仍走写连接（间接验证：SELECT 后 UPDATE/DELETE 一致） ──


async def test_rename_kb_doc_select_then_update_consistent():
    """rename_kb_doc 内部 SELECT 后 UPDATE 在同一写连接，原子可见。"""
    await db.create_kb({"kb_id": "kb1", "name": "n", "description": ""})
    await db.save_kb_doc({"doc_id": "d1", "kb_id": "kb1", "filename": "old.txt", "file_type": "txt"})
    assert await db.rename_kb_doc("d1", "new.txt") is True
    docs = await db.load_kb_docs("kb1")
    assert docs[0]["filename"] == "new.txt"
    # 不存在的 doc 返回 False
    assert await db.rename_kb_doc("nope", "x") is False


async def test_delete_kb_doc_returns_chunk_ids_and_cleans_two_tables():
    """delete_kb_doc SELECT chunk_ids 后 DELETE 两表，走同一写连接。"""
    await db.create_kb({"kb_id": "kb1", "name": "n", "description": ""})
    await db.save_kb_doc({"doc_id": "d1", "kb_id": "kb1", "filename": "f.txt", "file_type": "txt"})
    await db.save_kb_chunks(
        [
            {"chunk_id": "c1", "doc_id": "d1", "chunk_index": 0, "page": 0, "text": "a"},
            {"chunk_id": "c2", "doc_id": "d1", "chunk_index": 1, "page": 0, "text": "b"},
        ]
    )
    chunk_ids = await db.delete_kb_doc("d1")
    assert set(chunk_ids) == {"c1", "c2"}
    # 两表都应清空
    assert await db.load_kb_docs("kb1") == []
    assert await db.load_kb_chunk_texts(["c1", "c2"]) == {}


async def test_delete_kb_cascades_six_tables():
    """delete_kb 6 表级联 DELETE 走同一写连接，chunk_ids 返回正确。"""
    await db.create_kb({"kb_id": "kb1", "name": "n", "description": ""})
    await db.save_kb_doc({"doc_id": "d1", "kb_id": "kb1", "filename": "f.txt", "file_type": "txt"})
    await db.save_kb_chunks([{"chunk_id": "c1", "doc_id": "d1", "text": "x"}])
    await db.create_conversation({"conv_id": "v1", "kb_id": "kb1", "title": "t"})
    await db.save_message({"msg_id": "m1", "conv_id": "v1", "role": "user", "content": "hi"})

    chunk_ids = await db.delete_kb("kb1")
    assert chunk_ids == ["c1"]
    # 知识库及关联全清
    assert await db.load_kb("kb1") is None
    assert await db.load_kb_docs("kb1") == []
    assert await db.load_conversations("kb1") == []
    assert await db.load_messages("v1") == []


async def test_update_kb_select_then_update_returns_new_values():
    """update_kb SELECT 后 UPDATE 走写连接，返回合并后的字段。"""
    await db.create_kb({"kb_id": "kb1", "name": "old", "description": "desc"})
    # 只改 name，description 保留
    result = await db.update_kb("kb1", name="new")
    assert result == {"kb_id": "kb1", "name": "new", "description": "desc"}
    # 不存在的 kb 返回 None
    assert await db.update_kb("nope", name="x") is None


async def test_create_conversation_inserts_conversation_and_touches_kb():
    """create_conversation INSERT kb_conversations + UPDATE knowledge_bases 走写连接。"""
    await db.create_kb({"kb_id": "kb1", "name": "n", "description": ""})
    await db.create_conversation({"conv_id": "v1", "kb_id": "kb1", "title": "chat"})
    convs = await db.load_conversations("kb1")
    assert len(convs) == 1
    assert convs[0]["conv_id"] == "v1"
    # knowledge_bases.updated_at 应被更新（不报错即说明 UPDATE 成功）
    kb = await db.load_kb("kb1")
    assert kb is not None


async def test_save_kb_chunks_replaces_existing():
    """save_kb_chunks INSERT OR REPLACE 走写连接，重复 chunk_id 覆盖。"""
    await db.create_kb({"kb_id": "kb1", "name": "n", "description": ""})
    await db.save_kb_doc({"doc_id": "d1", "kb_id": "kb1", "filename": "f.txt", "file_type": "txt"})
    await db.save_kb_chunks([{"chunk_id": "c1", "doc_id": "d1", "text": "old"}])
    await db.save_kb_chunks([{"chunk_id": "c1", "doc_id": "d1", "text": "new"}])
    texts = await db.load_kb_chunk_texts(["c1"])
    assert texts["c1"]["text"] == "new"


# ── 6. 读连接读到写连接已提交的数据（WAL 可见性） ───────────────


async def test_read_connection_sees_committed_writes():
    """写连接 commit 后，读连接池借出的读连接能读到数据。"""
    await db.upsert_news([_news("vis1")])
    # 通过读连接查询
    got = await db.get_news("vis1")
    assert got is not None
    assert got["news_id"] == "vis1"
    _, total = await db.list_news()
    assert total == 1
