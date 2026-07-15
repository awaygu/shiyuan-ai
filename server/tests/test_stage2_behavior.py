"""阶段2 行为一致性抽查：DB 为事实来源 + 写顺序 + 去重 + 清空语义 + 分页排序 + 缓存失效。

这些测试验证实现 Agent 报告的改造行为确实成立，不改任何实现代码。
全部离线：真实 SQLite（tmp_path 隔离）+ 真实 jieba/BM25，无外部网络。
"""

from __future__ import annotations

import pytest

import database as db
from api import stores


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
async def _fresh_db_and_cache(monkeypatch, tmp_path):
    """每个测试独立 DB + 空缓存。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai.db")
    await db.close_db()
    monkeypatch.setattr(db, "_db", None)
    await db.init_db()
    stores.news_store.clear()
    stores.article_store.clear()
    stores.publish_log.clear()
    yield
    await db.close_db()
    stores.news_store.clear()
    stores.article_store.clear()
    stores.publish_log.clear()


# ── 1. DB 为事实来源：清空内存缓存后 find_news 仍能从 DB 回源命中 ──


async def test_find_news_survives_cache_clear_via_db_fallback():
    """upsert_news 落库后，清空内存缓存，find_news 仍应从 DB 回源命中。"""
    await db.upsert_news([_news("n1")])
    # 预热缓存
    await stores.find_news("n1")
    assert any(n["news_id"] == "n1" for n in stores.news_store)

    # 模拟"重启式"场景：清空内存缓存
    stores.invalidate_news()
    assert stores.news_store == []

    # find_news 应回源 DB 命中并回填缓存
    item = await stores.find_news("n1")
    assert item is not None
    assert item["news_id"] == "n1"
    assert any(n["news_id"] == "n1" for n in stores.news_store)


async def test_find_news_batch_survives_cache_clear():
    """find_news_batch 在缓存清空后也能从 DB 回源。"""
    await db.upsert_news([_news("a"), _news("b")])
    await stores.find_news_batch(["a", "b"])
    stores.invalidate_news()

    result = await stores.find_news_batch(["a", "b", "missing"])
    assert {r["news_id"] for r in result} == {"a", "b"}


# ── 2. 先 DB 后缓存的写顺序：upsert 后立即 get_news 可见 ──


async def test_upsert_then_immediate_db_read_visible():
    """先 DB 后缓存：upsert_news 返回后，DB 层 get_news 立即可见（无需缓存预热）。"""
    inserted = await db.upsert_news([_news("x1"), _news("x2")])
    assert inserted == 2
    # 不触碰缓存，直接查 DB
    assert await db.get_news("x1") is not None
    assert await db.get_news("x2") is not None
    _, total = await db.list_news()
    assert total == 2


async def test_upsert_dedup_returns_inserted_count_only():
    """upsert_news 用 INSERT OR IGNORE，重复 id 不计数。"""
    await db.upsert_news([_news("dup")])
    inserted = await db.upsert_news([_news("dup"), _news("new")])
    assert inserted == 1  # 只有 new 是新增
    _, total = await db.list_news()
    assert total == 2


# ── 3. 去重走 DB：news_id_exists_batch 行为正确 ──


async def test_news_id_exists_batch_atomic_dedup():
    """news_id_exists_batch 返回 DB 中已存在 id 集合，schedule 循环据此去重。"""
    await db.upsert_news([_news("a"), _news("b"), _news("c")])
    existing = await db.news_id_exists_batch(["a", "b", "c", "d", "e"])
    assert existing == {"a", "b", "c"}
    # 验证去重逻辑：未存在的才新增
    candidates = [_news("a"), _news("d"), _news("e")]
    new_items = [d for d in candidates if d["news_id"] not in existing]
    assert {d["news_id"] for d in new_items} == {"d", "e"}


async def test_schedule_loop_dedup_pattern_no_double_insert():
    """模拟 schedule 循环的 DB 查重模式：两轮同 id 不应重复入库。"""
    candidates = [_news("dup"), _news("fresh")]

    # 第一轮：全部新增
    existing = await db.news_id_exists_batch([c["news_id"] for c in candidates])
    new_items = [c for c in candidates if c["news_id"] not in existing]
    await db.upsert_news(new_items)
    assert len(new_items) == 2

    # 第二轮：dup 已存在，只有 fresh 应"新增"（实际为 0，因为 fresh 也已存在）
    existing2 = await db.news_id_exists_batch([c["news_id"] for c in candidates])
    new_items2 = [c for c in candidates if c["news_id"] not in existing2]
    assert new_items2 == []
    _, total = await db.list_news()
    assert total == 2  # 无重复


# ── 4. agent refresh_news 清空语义：delete_all_news + 重灌后旧 id 不可见 ──


async def test_refresh_news_clears_then_reinserts_old_ids_gone():
    """refresh_news 语义：delete_all_news + 重灌新数据后，旧 news_id 不再可见。"""
    await db.upsert_news([_news("old1"), _news("old2"), _news("keep")])
    assert (await db.get_news("old1")) is not None

    # 模拟 agent refresh_news：清空 + 重灌（只含 keep 和 new）
    await db.delete_all_news()
    await db.upsert_news([_news("keep"), _news("new1")])

    # 旧 id 不可见
    assert await db.get_news("old1") is None
    assert await db.get_news("old2") is None
    # 保留的和新增的可见
    assert await db.get_news("keep") is not None
    assert await db.get_news("new1") is not None
    _, total = await db.list_news()
    assert total == 2


async def test_delete_all_news_then_empty_list():
    """delete_all_news 后 list_news 返回空。"""
    await db.upsert_news([_news("a"), _news("b")])
    await db.delete_all_news()
    items, total = await db.list_news()
    assert total == 0
    assert items == []


# ── 5. 分页与排序 ──


async def test_list_news_orders_by_published_at_desc():
    """list_news 按 published_at DESC 排序。"""
    await db.upsert_news(
        [
            _news("old", published_at="2024-01-01T00:00:00"),
            _news("new", published_at="2024-12-01T00:00:00"),
            _news("mid", published_at="2024-06-01T00:00:00"),
        ]
    )
    page, total = await db.list_news(offset=0, limit=10)
    assert total == 3
    assert [p["news_id"] for p in page] == ["new", "mid", "old"]


async def test_list_news_pagination_consistent_total():
    """list_news 分页时 total 始终为全量，与 offset/limit 无关。"""
    items = [_news(f"n{i}", published_at=f"2024-01-{i + 1:02d}T00:00:00") for i in range(5)]
    await db.upsert_news(items)
    p1, t1 = await db.list_news(offset=0, limit=2)
    p2, t2 = await db.list_news(offset=2, limit=2)
    p3, t3 = await db.list_news(offset=4, limit=2)
    assert t1 == t2 == t3 == 5
    assert [p["news_id"] for p in p1] == ["n4", "n3"]
    assert [p["news_id"] for p in p2] == ["n2", "n1"]
    assert [p["news_id"] for p in p3] == ["n0"]


async def test_list_news_source_filter_total():
    """list_news 带 source 时 total 只计该 source。"""
    await db.upsert_news(
        [
            _news("a1", source="cls-hot"),
            _news("a2", source="cls-hot"),
            _news("b1", source="rss-x"),
        ]
    )
    page, total = await db.list_news(source="cls-hot", offset=0, limit=10)
    assert total == 2
    assert {p["news_id"] for p in page} == {"a1", "a2"}


async def test_list_articles_orders_by_created_at_desc():
    """list_articles 按 created_at DESC。

    created_at 由 DEFAULT datetime('now') 生成（秒级精度），快速连续插入可能
    产生相同时间戳导致排序不确定。这里通过原始 SQL 插入明确不同的 created_at
    以稳定验证 ORDER BY 子句方向（不依赖生产写入路径的时间精度）。
    """
    conn = await db.get_db()
    for i, ts in enumerate(["2024-01-01 00:00:00", "2024-06-01 00:00:00", "2024-12-01 00:00:00"]):
        await conn.execute(
            "INSERT INTO articles (article_id, title, content, style, news_ids, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f"art_{i}", f"t{i}", "c", "s", "[]", ts),
        )
    await conn.commit()

    page, total = await db.list_articles(offset=0, limit=10)
    assert total == 3
    assert [p["article_id"] for p in page] == ["art_2", "art_1", "art_0"]


async def test_list_publish_log_orders_by_id_desc():
    """list_publish_log 按 id DESC（自增 id，最新插入排最前）。"""
    for i in range(4):
        await db.save_publish_record(
            {
                "article_id": f"art_{i}",
                "platform": "xiaohongshu",
                "success": True,
                "url": "",
                "timestamp": f"2024-01-0{i + 1}T00:00:00",
                "extra": {},
            }
        )
    page, total = await db.list_publish_log(offset=0, limit=10)
    assert total == 4
    # 最后插入的（art_3）id 最大，排最前
    assert page[0]["article_id"] == "art_3"
    assert page[-1]["article_id"] == "art_0"


# ── 6. 缓存失效：invalidate 后下次读回源 DB ──


async def test_invalidate_news_then_find_news_refetches_from_db():
    """invalidate_news(news_id=...) 后下次 find_news 回源 DB 回填（拿到的不是旧缓存对象）。"""
    await db.upsert_news([_news("n1")])
    cached = await stores.find_news("n1")
    cached["content"] = "dirty"  # 模拟缓存被污染

    stores.invalidate_news(news_id="n1")
    assert not any(n["news_id"] == "n1" for n in stores.news_store)

    refetched = await stores.find_news("n1")
    assert refetched is not None
    assert refetched["content"] == ""  # 回源 DB，不是脏缓存


async def test_invalidate_articles_then_find_article_refetches():
    """invalidate_articles 后 find_article 回源 DB。"""
    await db.save_article(
        {"article_id": "art_1", "title": "t", "content": "c", "style": "s", "news_ids": ["n1"]}
    )
    cached = await stores.find_article("art_1")
    assert cached is not None
    cached["title"] = "dirty"

    stores.invalidate_articles()
    assert stores.article_store == []

    refetched = await stores.find_article("art_1")
    assert refetched["title"] == "t"  # 回源 DB


async def test_invalidate_news_by_source_then_list_refetches():
    """invalidate_news(source=...) 移除该 source 缓存条目，find_news 回源 DB。"""
    await db.upsert_news([_news("a", source="cls-hot"), _news("b", source="rss-x")])
    stores.news_store.extend(await db.load_news())
    stores.invalidate_news(source="cls-hot")
    assert {n["news_id"] for n in stores.news_store} == {"b"}

    # find_news("a") 应回源 DB
    item = await stores.find_news("a")
    assert item is not None
    assert item["source"] == "cls-hot"
