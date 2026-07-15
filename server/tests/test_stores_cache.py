"""Tests for stores.py cache + lookup helpers (DB-backing).

Verifies the "DB as source of truth + in-memory cache with fallback" model:
- find_news / find_article return cached objects on hit, query DB on miss and
  backfill the cache.
- In-place mutations of a returned cached item keep the cache fresh.
- Invalidation helpers drop cache entries.
"""

from __future__ import annotations

import pytest

import database as db
from api import stores


def _news(news_id: str, source: str = "cls-hot") -> dict:
    return {
        "news_id": news_id,
        "title": f"title-{news_id}",
        "summary": f"summary-{news_id}",
        "content": "",
        "source": source,
        "url": f"https://example.com/{news_id}",
        "published_at": "2024-01-01T00:00:00",
        "extra": {"media_type": "article"},
    }


@pytest.fixture(autouse=True)
async def _fresh_db_and_cache(monkeypatch, tmp_path):
    """Fresh DB + empty caches per test."""
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


async def test_find_news_miss_queries_db_and_backfills_cache():
    await db.upsert_news([_news("n1")])
    # cache empty -> miss -> DB hit -> backfill
    item = await stores.find_news("n1")
    assert item is not None
    assert item["news_id"] == "n1"
    # now cached
    assert any(n["news_id"] == "n1" for n in stores.news_store)


async def test_find_news_hit_returns_cached_shared_object():
    await db.upsert_news([_news("n1")])
    first = await stores.find_news("n1")
    second = await stores.find_news("n1")
    # same shared object (in-place mutation semantics preserved)
    assert first is second


async def test_find_news_inplace_update_keeps_cache_fresh():
    await db.upsert_news([_news("n1")])
    item = await stores.find_news("n1")
    item["content"] = "fetched body"
    # cache reflects the mutation (no re-read from DB needed)
    cached = next(n for n in stores.news_store if n["news_id"] == "n1")
    assert cached["content"] == "fetched body"


async def test_find_news_missing_returns_none():
    assert await stores.find_news("nope") is None
    # nothing backfilled
    assert stores.news_store == []


async def test_find_news_batch_mixes_cache_and_db():
    await db.upsert_news([_news("a"), _news("b"), _news("c")])
    # prime cache with "a" only
    await stores.find_news("a")
    result = await stores.find_news_batch(["a", "b", "c", "missing"])
    ids = {r["news_id"] for r in result}
    assert ids == {"a", "b", "c"}
    # b and c now backfilled
    cached_ids = {n["news_id"] for n in stores.news_store}
    assert {"a", "b", "c"}.issubset(cached_ids)


async def test_find_news_batch_empty_returns_empty():
    assert await stores.find_news_batch([]) == []


async def test_find_article_miss_queries_db_and_backfills():
    await db.save_article(
        {"article_id": "art_1", "title": "t", "content": "c", "style": "s", "news_ids": ["n1"]}
    )
    art = await stores.find_article("art_1")
    assert art is not None
    assert art["article_id"] == "art_1"
    assert any(a["article_id"] == "art_1" for a in stores.article_store)


async def test_invalidate_news_clears_all():
    await db.upsert_news([_news("a"), _news("b")])
    stores.news_store.extend(await db.load_news())
    stores.invalidate_news()
    assert stores.news_store == []


async def test_invalidate_news_by_id_removes_entry():
    await db.upsert_news([_news("a"), _news("b")])
    stores.news_store.extend(await db.load_news())
    stores.invalidate_news(news_id="a")
    assert {n["news_id"] for n in stores.news_store} == {"b"}


async def test_invalidate_news_by_source_removes_matching():
    await db.upsert_news([_news("a", source="cls-hot"), _news("b", source="rss-x")])
    stores.news_store.extend(await db.load_news())
    stores.invalidate_news(source="cls-hot")
    assert {n["news_id"] for n in stores.news_store} == {"b"}


async def test_invalidate_articles_and_publish_log_clear_caches():
    stores.article_store.append({"article_id": "x"})
    stores.publish_log.append({"platform": "p"})
    stores.invalidate_articles()
    stores.invalidate_publish_log()
    assert stores.article_store == []
    assert stores.publish_log == []
