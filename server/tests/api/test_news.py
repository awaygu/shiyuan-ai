"""Tests for news-related API routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi.testclient import TestClient

from sources.base import NewsItem


def _item(news_id: str, source: str = "cls-hot") -> NewsItem:
    return NewsItem(
        news_id=news_id,
        title=f"title-{news_id}",
        summary=f"summary-{news_id}",
        source=source,
        url=f"https://example.com/{news_id}",
    )


def test_get_news_empty(client: TestClient) -> None:
    """GET /api/news should return an empty list on a fresh database."""
    response = client.get("/api/news")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["offset"] == 0
    assert data["limit"] == 20


def test_get_news_by_source_empty(client: TestClient) -> None:
    """GET /api/news?source=... should return an empty list for unknown sources."""
    response = client.get("/api/news?source=cls-hot")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_refresh_news_mocked(client: TestClient) -> None:
    """POST /api/news/refresh should work without real crawlers."""
    response = client.post("/api/news/refresh")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["new"] == 0
    assert data["total_raw"] == 0
    assert "results" in data


def test_refresh_then_list_visible_immediately(client: TestClient, monkeypatch) -> None:
    """After refresh writes to DB, list should see the new items immediately.

    Validates the "DB first write" visibility guarantee: no in-memory cache
    priming is required because /api/news reads from DB.
    """
    import api.crawlers as crawlers
    from api import deps

    # Disable keyword filter so the synthetic test items survive filtering.
    monkeypatch.setattr(deps.kw_filter, "enabled", False)

    items = [_item("n1", "cls-hot"), _item("n2", "rss-y")]

    async def _newsnow_items():
        return {"p1": [items[0]]}

    async def _rss_items():
        return {"feed1": [items[1]]}

    monkeypatch.setattr(crawlers.newsnow_batch, "crawl_all", _newsnow_items)
    monkeypatch.setattr(crawlers.rss_batch, "crawl_all", _rss_items)

    refresh = client.post("/api/news/refresh")
    assert refresh.status_code == 200
    rdata = refresh.json()
    assert rdata["new"] == 2
    assert rdata["total"] == 2  # DB count, consistent with list endpoint

    listed = client.get("/api/news?limit=10")
    assert listed.status_code == 200
    ldata = listed.json()
    assert ldata["total"] == 2
    ids = {it["news_id"] for it in ldata["items"]}
    assert ids == {"n1", "n2"}


def test_refresh_dedupes_existing_ids_via_db(client: TestClient, monkeypatch) -> None:
    """A second refresh with overlapping news_ids should not duplicate (DB dedup)."""
    import api.crawlers as crawlers
    from api import deps

    monkeypatch.setattr(deps.kw_filter, "enabled", False)

    async def _newsnow_items():
        return {"p1": [_item("dup"), _item("fresh")]}

    async def _rss_items():
        return {}

    monkeypatch.setattr(crawlers.newsnow_batch, "crawl_all", _newsnow_items)
    monkeypatch.setattr(crawlers.rss_batch, "crawl_all", _rss_items)

    client.post("/api/news/refresh")
    # 第二次：dup 已存在，只有 fresh 是新增
    client.post("/api/news/refresh")
    listed = client.get("/api/news?limit=10")
    ldata = listed.json()
    assert ldata["total"] == 2
    ids = {it["news_id"] for it in ldata["items"]}
    assert ids == {"dup", "fresh"}


def test_trends_reads_cache_after_refresh(client: TestClient, monkeypatch) -> None:
    """trends endpoint reads the news_store cache; refresh backfills it.

    Ensures the cache-backed scan endpoints (trends/search/briefing) still
    work after refresh, which backfills the cache via extend.
    """
    import api.crawlers as crawlers
    from api import deps

    monkeypatch.setattr(deps.kw_filter, "enabled", False)

    async def _newsnow_items():
        return {"p1": [_item("trend1", "cls-hot")]}

    async def _rss_items():
        return {}

    monkeypatch.setattr(crawlers.newsnow_batch, "crawl_all", _newsnow_items)
    monkeypatch.setattr(crawlers.rss_batch, "crawl_all", _rss_items)

    # Before refresh: cache empty -> trends reports no data.
    pre = client.get("/api/agent/trends")
    assert pre.status_code == 200
    assert pre.json()["total_news"] == 0

    client.post("/api/news/refresh")

    # After refresh: cache backfilled -> trends sees the item.
    post = client.get("/api/agent/trends")
    assert post.status_code == 200
    assert post.json()["total_news"] == 1


def test_refresh_news_source_registers_short_task(client: TestClient, monkeypatch):
    """POST /api/news/refresh/{source} 应经 task_manager.register_short 登记后台 task。"""
    from api import deps
    from api.tasks import task_manager

    task_manager._short_tasks.clear()
    captured: list = []
    _orig_register = task_manager.register_short

    def _spy_register_short(t):
        captured.append(t)
        _orig_register(t)

    monkeypatch.setattr(task_manager, "register_short", _spy_register_short)

    # mock 单个爬虫的 crawl 返回空，避免真实网络（15s 超时）
    async def _empty_crawl():
        return []

    crawler = deps.NEWSNOW_CRAWLERS["cls-hot"]
    monkeypatch.setattr(crawler, "crawl", _empty_crawl)

    resp = client.post("/api/news/refresh/cls-hot")
    assert resp.status_code == 200
    assert resp.json()["status"] == "refreshing"
    assert len(captured) == 1
    # task 是 _bg_crawl_and_save，内部吞掉爬取异常并 return，会很快完成。
    # TestClient 退出上下文时会清理；这里不强等。


def test_refresh_newsnow_platform_registers_short_task(client: TestClient, monkeypatch):
    """POST /api/newsnow/refresh/{platform_id} 应经 task_manager.register_short 登记。"""
    from api import deps
    from api.tasks import task_manager

    task_manager._short_tasks.clear()
    captured: list = []
    _orig_register = task_manager.register_short
    monkeypatch.setattr(task_manager, "register_short", lambda t: (captured.append(t), _orig_register(t)))

    async def _empty_crawl():
        return []

    crawler = deps.NEWSNOW_CRAWLERS["cls-hot"]
    monkeypatch.setattr(crawler, "crawl", _empty_crawl)

    resp = client.post("/api/newsnow/refresh/cls-hot")
    assert resp.status_code == 200
    assert resp.json()["status"] == "refreshing"
    assert len(captured) == 1


async def test_bg_crawl_and_save_unhandled_exception_logged(monkeypatch, caplog):
    """register_short 登记的 task 若抛出未捕获异常，done_callback 应 logger.error
    记录（异常可观测）。

    _bg_crawl_and_save 内部 try/except 只包住 crawl()；事务/回填阶段抛出的异常
    会冒泡到 task 层面，由 register_short 的 done_callback 记录。这里直接构造一个
    必然抛错的 task 验证记录链路。
    """
    from api.tasks import task_manager

    task_manager._short_tasks.clear()

    async def _raise():
        raise RuntimeError("unhandled in bg")

    task = asyncio.create_task(_raise())
    task_manager.register_short(task)
    with caplog.at_level(logging.ERROR):
        await asyncio.gather(task, return_exceptions=True)
    # 让 done_callback 有机会执行
    await asyncio.sleep(0)
    assert any("短期后台任务异常" in r.getMessage() and r.levelno == logging.ERROR for r in caplog.records)
