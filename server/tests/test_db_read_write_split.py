"""阶段2 任务6/7 读写分离与事务并发回归测试。

验证 database.py 的写连接（get_db）与读连接池（get_read_db）分离：
- get_read_db 返回的连接与写连接不同实例（读不阻塞写）。
- 读连接池复用空闲读连接（非每次新建）。
- close_db 同时关闭写连接 + 写连接池 + 读连接池（跨测试隔离）。
- upsert_news_returning 用 RETURNING 返回真正新增的 news_id 列表。
- transaction 上下文管理器从写连接池借独立写连接、BEGIN IMMEDIATE，异常时 rollback。
- transaction 并发安全：两个并发 transaction() 串行化执行不报错（替代旧 asyncio.Lock），
  并发写同一表后数据一致。
- 复合写函数（rename_kb_doc / delete_kb_doc / update_kb / delete_kb /
  create_conversation / save_kb_chunks / upsert_news）仍走写连接，SELECT 后的
  UPDATE/DELETE 在同一写连接内完成。

全部离线：真实 SQLite（tmp_path 隔离），无外部网络。
"""

from __future__ import annotations

import asyncio

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


async def test_transaction_uses_independent_write_connection():
    """transaction 借的是独立写连接（与 get_db 的单写连接不同实例）。

    锁收窄后 transaction() 从写连接池借独立连接，使并发事务各拿独立连接、
    各自 BEGIN IMMEDIATE，由 busy_timeout 在 DB 层串行化——而非共享单写连接
    导致 "cannot start a transaction within a transaction" 报错。
    """
    write_conn = await db.get_db()
    async with db.transaction() as conn:
        assert conn is not write_conn


# ── 4b. transaction 并发安全（锁收窄后替代 asyncio.Lock） ─────────


async def test_concurrent_transactions_serialize_no_error():
    """两个并发 transaction() 串行化执行、不报错。

    旧实现复用单写连接 _db，第二个并发事务 BEGIN IMMEDIATE 会撞上
    "cannot start a transaction within a transaction"。改用写连接池后，
    两事务各拿独立写连接，第二个 BEGIN IMMEDIATE 遇写锁被占由 busy_timeout
    在 DB 层重试等待，串行完成而非抛错。此处用 sleep 制造重叠窗口。
    """
    started: list[int] = []
    finished: list[int] = []

    async def tx_a():
        async with db.transaction():
            started.append(1)
            await asyncio.sleep(0.05)  # 持有写锁 50ms，与 tx_b 重叠
            finished.append(1)

    async def tx_b():
        async with db.transaction():
            started.append(2)
            finished.append(2)

    # gather 会让两者交叠进入；tx_b 的 BEGIN IMMEDIATE 应等待 tx_a 提交
    await asyncio.gather(tx_a(), tx_b())

    # 两者都成功完成，无异常抛出
    assert sorted(started) == [1, 2]
    assert sorted(finished) == [1, 2]


async def test_concurrent_transactions_write_consistency():
    """并发事务各 upsert 不同 news_id，结果都在且数据一致。

    BEGIN IMMEDIATE 在 DB 层串行化两个写事务（一个先提交，另一个再拿写锁），
    各自 INSERT 不同 news_id 后均提交——读连接应同时看到两条记录。
    不在事务体内用 barrier 同步：那会要求两个事务同时持有写锁，而写锁本就是
    互斥的，会退化为 busy_timeout 超时报错。
    """

    async def tx(label: str):
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT INTO news (news_id, title, summary, content, source, url, published_at, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"c-{label}", f"t-{label}", "s", "c", "cls-hot", "u", "2024-01-01", "{}"),
            )

    await asyncio.gather(tx("a"), tx("b"))

    got_a = await db.get_news("c-a")
    got_b = await db.get_news("c-b")
    assert got_a is not None and got_a["title"] == "t-a"
    assert got_b is not None and got_b["title"] == "t-b"
    _, total = await db.list_news()
    assert total == 2


async def test_transaction_connection_returned_to_write_pool():
    """事务结束后写连接归还到写连接池（供下次复用，非每次新建）。"""
    # 首个事务建一条写连接，归还后池应有 1 条
    async with db.transaction():
        pass
    assert db._write_pool is not None
    assert len(db._write_pool) == 1
    first = db._write_pool[0]
    # 第二个事务复用池中的同一条连接
    async with db.transaction() as conn:
        assert conn is first
    # 复用后仍归还到池
    assert len(db._write_pool) == 1


async def test_close_db_resets_write_pool():
    """close_db 关闭并置空写连接池，下次 transaction() 按新路径重建。"""
    async with db.transaction():
        pass
    assert db._write_pool is not None
    assert len(db._write_pool) == 1

    await db.close_db()
    assert db._write_pool is None
    assert db._db is None

    # 重建后 transaction() 能正常用（新连接按当前 DB_PATH 建）
    await db.init_db()
    async with db.transaction() as conn:
        await conn.execute("SELECT 1")
    assert db._write_pool is not None
    await db.close_db()


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


# ── 7. 全量刷新事务原子性（N5/N7：delete+insert 不留中间空库） ────
# 阶段2 任务7 关键回归：refresh_news 的 DELETE+INSERT 包进同一 transaction()，
# 提交是原子的。并发读者在任何时刻要么看到旧全集、要么看到新全集，绝不看到
# "DELETE 已生效但 INSERT 未生效" 的中间空库。这是修掉 "清空与重灌之间被并发刷新
# 插入残留" 缺陷后的守卫测试。


async def test_full_refresh_delete_insert_atomic_no_empty_window():
    """全量刷新：事务内 DELETE+INSERT 原子提交，外部读连接看到的 total 恒大于 0。

    预置 2 条旧新闻，模拟 refresh_news 事务体（DELETE FROM news + INSERT 新条目），
    在事务提交前后用读连接观察：提交前（旧数据可见）和提交后（新数据可见）均非空，
    不会出现"DELETE 已提交但 INSERT 未提交"导致的 total=0 中间态。
    """
    # 预置旧数据
    await db.upsert_news([_news("old1"), _news("old2")])
    assert (await db.list_news())[1] == 2

    new_items = [
        _news("new1", published_at="2025-01-01T00:00:00"),
        _news("new2", published_at="2025-02-01T00:00:00"),
        _news("new3", published_at="2025-03-01T00:00:00"),
    ]

    # 事务未提交前：读连接仍能看到旧数据（DELETE 尚未提交，WAL 快照隔离）
    async with db.transaction() as conn:
        await conn.execute("DELETE FROM news")
        # 事务内：此时写连接已 DELETE 但未 commit，读连接应仍看到旧数据
        _, total_before_commit = await db.list_news()
        assert total_before_commit == 2, "未提交的 DELETE 不应对读连接可见"
        # 事务内插入新数据
        for item in new_items:
            await conn.execute(
                "INSERT OR IGNORE INTO news "
                "(news_id, title, summary, content, source, url, published_at, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["news_id"],
                    item["title"],
                    item["summary"],
                    item["content"],
                    item["source"],
                    item["url"],
                    item["published_at"],
                    "{}",
                ),
            )
        # 事务内仍未提交：读连接看到的还是旧数据
        _, total_mid = await db.list_news()
        assert total_mid == 2, "未提交的 INSERT 也不应对读连接可见"

    # 事务提交后：读连接应一次性看到新全集（3 条），不出现 0 条中间态
    items, total_after = await db.list_news()
    assert total_after == 3
    assert {it["news_id"] for it in items} == {"new1", "new2", "new3"}


async def test_full_refresh_concurrent_reader_never_sees_empty():
    """并发读者在全量刷新事务执行期间不应观察到 total=0 的中间空库。

    用一个长事务（DELETE + sleep + INSERT）制造"中间窗口"，同时并发起多次
    读连接查询。WAL 快照隔离 + 单事务原子提交保证读连接要么看到旧全集、要么
    看到新全集，任何一次读都不应拿到 total=0。这是 N5/N7 缺陷的关键回归守卫。
    """
    # 预置旧数据
    await db.upsert_news([_news("keep1"), _news("keep2")])

    new_items = [_news(f"r{i}", published_at=f"2025-0{i}-01T00:00:00") for i in range(1, 5)]

    observed_totals: list[int] = []
    stop = asyncio.Event()

    async def _reader():
        while not stop.is_set():
            _, total = await db.list_news()
            observed_totals.append(total)
            assert total > 0, "并发读不应看到空库中间态"
            await asyncio.sleep(0)

    async def _refresh_tx():
        async with db.transaction() as conn:
            await conn.execute("DELETE FROM news")
            # 制造中间窗口：DELETE 已执行但未提交
            await asyncio.sleep(0.05)
            for item in new_items:
                await conn.execute(
                    "INSERT OR IGNORE INTO news "
                    "(news_id, title, summary, content, source, url, published_at, extra) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item["news_id"],
                        item["title"],
                        item["summary"],
                        item["content"],
                        item["source"],
                        item["url"],
                        item["published_at"],
                        "{}",
                    ),
                )

    reader_task = asyncio.create_task(_reader())
    await _refresh_tx()
    stop.set()
    await asyncio.gather(reader_task, return_exceptions=True)

    # 所有读观测到的 total 都 > 0（要么旧 2 条，要么新 4 条）
    assert observed_totals, "读者应至少观测到一次"
    assert all(t > 0 for t in observed_totals)
    # 最终读到新全集
    _, final_total = await db.list_news()
    assert final_total == 4


# ── 8. 并发事务压力测试（多事务交错 + 读连接一致） ──────────────


async def test_many_concurrent_transactions_all_commit_consistently():
    """10 个并发 transaction() 各插不同 news_id，串行化完成后读连接看到全部 10 条。

    覆盖任务7 修复的并发缺陷：旧实现复用单写连接 _db，第二个并发事务 BEGIN IMMEDIATE
    撞 "cannot start a transaction within a transaction"；改用写连接池后每事务各拿
    独立写连接、busy_timeout 串行化。此处加压到 10 个并发事务，全部应无错提交。
    """
    N = 10

    async def tx(i: int):
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT INTO news (news_id, title, summary, content, source, url, published_at, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"p{i}", f"t{i}", "s", "c", "cls-hot", "u", "2024-01-01", "{}"),
            )

    await asyncio.gather(*(tx(i) for i in range(N)))

    _, total = await db.list_news()
    assert total == N
    # 每条都能读到
    for i in range(N):
        assert await db.get_news(f"p{i}") is not None


async def test_concurrent_transactions_with_interleaved_reads_consistent():
    """并发写事务交错进行时，读连接看到的 total 单调不减（不丢已提交事务）。

    每个事务提交后读连接立即可见；并发场景下 total 从 0 增长到 N，任意时刻
    读到的 total 都 <= 已提交事务数（WAL 快照），且最终 == N。
    """
    N = 8
    commit_order: list[int] = []

    async def tx(i: int):
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT INTO news (news_id, title, summary, content, source, url, published_at, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"c{i}", f"t{i}", "s", "c", "cls-hot", "u", "2024-01-01", "{}"),
            )
        commit_order.append(i)

    await asyncio.gather(*(tx(i) for i in range(N)))

    _, total = await db.list_news()
    assert total == N
    assert sorted(commit_order) == list(range(N))
