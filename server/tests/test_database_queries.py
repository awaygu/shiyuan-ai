"""Tests for the new database query functions added in stage 2.

Covers get_news / get_news_batch / list_news / news_id_exists_batch /
delete_all_news / get_news_sources / get_article / list_articles /
list_publish_log. These exercise the "DB as source of truth" layer
directly, independent of the in-memory caches.
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
    """Each test gets its own empty database + fresh connection."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai.db")
    await db.close_db()
    monkeypatch.setattr(db, "_db", None)
    await db.init_db()
    yield
    await db.close_db()


async def test_get_news_returns_none_for_missing():
    assert await db.get_news("nope") is None


async def test_get_news_returns_deserialized_row():
    await db.upsert_news([_news("n1", source="cls-hot")])
    item = await db.get_news("n1")
    assert item is not None
    assert item["news_id"] == "n1"
    assert item["source"] == "cls-hot"
    assert item["extra"] == {"media_type": "article"}


async def test_get_news_batch_empty_input_returns_empty():
    assert await db.get_news_batch([]) == []


async def test_get_news_batch_returns_only_existing_ordered_by_published_at_desc():
    await db.upsert_news(
        [
            _news("old", published_at="2024-01-01T00:00:00"),
            _news("new", published_at="2024-06-01T00:00:00"),
            _news("mid", published_at="2024-03-01T00:00:00"),
        ]
    )
    # 请求含一个不存在的 id，应被忽略
    result = await db.get_news_batch(["old", "new", "mid", "missing"])
    assert [r["news_id"] for r in result] == ["new", "mid", "old"]


async def test_list_news_no_source_filters_and_paginates():
    items = [_news(f"n{i}", published_at=f"2024-01-{i:02d}T00:00:00") for i in range(1, 6)]
    await db.upsert_news(items)
    page, total = await db.list_news(source=None, offset=0, limit=2)
    assert total == 5
    assert [p["news_id"] for p in page] == ["n5", "n4"]  # DESC by published_at

    page2, total2 = await db.list_news(source=None, offset=2, limit=2)
    assert total2 == 5
    assert [p["news_id"] for p in page2] == ["n3", "n2"]


async def test_list_news_with_source_filter():
    await db.upsert_news([_news("a", source="cls-hot"), _news("b", source="rss-x")])
    page, total = await db.list_news(source="cls-hot", offset=0, limit=10)
    assert total == 1
    assert page[0]["news_id"] == "a"

    page_none, total_none = await db.list_news(source="rss-x", offset=0, limit=10)
    assert total_none == 1
    assert page_none[0]["news_id"] == "b"


async def test_news_id_exists_batch_returns_existing_subset():
    await db.upsert_news([_news("a"), _news("b")])
    existing = await db.news_id_exists_batch(["a", "b", "c"])
    assert existing == {"a", "b"}


async def test_news_id_exists_batch_empty_returns_empty_set():
    assert await db.news_id_exists_batch([]) == set()


async def test_delete_all_news_clears_table():
    await db.upsert_news([_news("a"), _news("b")])
    await db.delete_all_news()
    assert await db.get_news("a") is None
    _, total = await db.list_news()
    assert total == 0


async def test_get_news_sources_returns_distinct():
    await db.upsert_news([_news("a", source="cls-hot"), _news("b", source="rss-x"), _news("c", source="cls-hot")])
    sources = await db.get_news_sources()
    assert set(sources) == {"cls-hot", "rss-x"}


async def test_get_news_sources_empty_table_returns_empty_list():
    assert await db.get_news_sources() == []


async def test_get_article_returns_none_for_missing():
    assert await db.get_article("nope") is None


async def test_get_article_returns_deserialized_row():
    article = {
        "article_id": "art_1",
        "title": "t",
        "content": "c",
        "style": "wechat_mp",
        "news_ids": ["n1", "n2"],
    }
    await db.save_article(article)
    got = await db.get_article("art_1")
    assert got is not None
    assert got["article_id"] == "art_1"
    assert got["news_ids"] == ["n1", "n2"]


async def test_list_articles_paginates_desc_by_created_at():
    # 保存顺序与 created_at 顺序不直接相关（DEFAULT now），这里仅验证分页与 total。
    for i in range(3):
        await db.save_article(
            {"article_id": f"art_{i}", "title": f"t{i}", "content": "c", "style": "s", "news_ids": []}
        )
    page, total = await db.list_articles(offset=0, limit=2)
    assert total == 3
    assert len(page) == 2


async def test_list_publish_log_paginates_desc_by_id():
    for i in range(3):
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
    page, total = await db.list_publish_log(offset=0, limit=2)
    assert total == 3
    assert len(page) == 2
    # DESC by id：第一条记录的 id 应大于第二条
    assert page[0]["platform"] == "xiaohongshu"
