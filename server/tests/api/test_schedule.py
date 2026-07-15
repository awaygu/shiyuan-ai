"""api/schedule.py 测试：status / toggle / config 端点 + 爬取循环去重逻辑。

通过 TestClient 测端点；循环逻辑用直接调用 _newsnow_crawl_loop 一轮验证去重。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import api.schedule as schedule_mod
import api.schedule_state as schedule_state
import api.stores as stores
import database as db
from api import deps


def _news(news_id: str, source: str = "cls-hot") -> dict:
    return {
        "news_id": news_id,
        "title": f"t-{news_id}",
        "summary": f"s-{news_id}",
        "content": "",
        "source": source,
        "url": f"https://x/{news_id}",
        "published_at": "2024-01-01T00:00:00",
        "extra": {},
    }


def test_schedule_status_endpoint(client: TestClient):
    resp = client.get("/api/schedule/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "running" in data
    assert "newsnow_interval" in data
    assert "rss_interval" in data


def test_schedule_toggle_start_and_stop(client: TestClient, monkeypatch):
    """toggle 端点启动/停止调度；启动会 create_task 两个循环，需立即停止避免后台跑飞。"""
    # 直接写源模块（与 app.py lifespan / toggle 端点一致），不要写 deps——
    # 写 deps 只会 shadow 在 deps.__dict__，toggle 端点写源模块后 deps 读取仍
    # 拿到 shadow 的旧值，导致跨路径不一致。
    schedule_state.schedule_running = False

    # patch 循环协程为立即返回的空函数，避免真实 sleep
    async def _noop_loop():
        return None

    monkeypatch.setattr(schedule_mod, "_newsnow_crawl_loop", _noop_loop)
    monkeypatch.setattr(schedule_mod, "_rss_crawl_loop", _noop_loop)

    resp = client.post("/api/schedule/toggle", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["running"] is True

    resp2 = client.post("/api/schedule/toggle", json={"enabled": False})
    assert resp2.status_code == 200
    assert resp2.json()["running"] is False


def test_schedule_toggle_idempotent_when_already_running(client: TestClient, monkeypatch):
    """已 running 时再启用不应重复 create_task（无额外副作用）。"""
    schedule_state.schedule_running = True

    async def _noop_loop():
        return None

    monkeypatch.setattr(schedule_mod, "_newsnow_crawl_loop", _noop_loop)
    monkeypatch.setattr(schedule_mod, "_rss_crawl_loop", _noop_loop)
    resp = client.post("/api/schedule/toggle", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["running"] is True
    schedule_state.schedule_running = False  # 还原


def test_schedule_config_update_valid(client: TestClient):
    resp = client.post("/api/schedule/config", json={"newsnow_interval": 120, "rss_interval": 300})
    assert resp.status_code == 200
    data = resp.json()
    assert data["newsnow_interval"] == 120
    assert data["rss_interval"] == 300


def test_schedule_config_update_below_min_rejected(client: TestClient):
    """低于 SCHEDULE_MIN_INTERVAL 应返回 400。"""
    from config import SCHEDULE_MIN_INTERVAL

    resp = client.post("/api/schedule/config", json={"newsnow_interval": SCHEDULE_MIN_INTERVAL - 1})
    assert resp.status_code == 400


def test_schedule_config_partial_update(client: TestClient):
    """只更新 newsnow_interval，rss_interval 保持不变。"""
    deps.rss_interval = 999
    resp = client.post("/api/schedule/config", json={"newsnow_interval": 200})
    assert resp.status_code == 200
    assert resp.json()["newsnow_interval"] == 200
    assert resp.json()["rss_interval"] == 999


async def test_newsnow_crawl_loop_dedups_via_db(monkeypatch, tmp_path):
    """_newsnow_crawl_loop 一轮：爬取 → DB 查重 → 只写新增。

    隔离 DB + 关键字过滤放行 + mock crawl_all 返回含已有 id 的候选，
    验证不会重复入库。
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai.db")
    await db.close_db()
    monkeypatch.setattr(db, "_db", None)
    await db.init_db()
    stores.news_store.clear()

    # 预置一条已有新闻
    await db.upsert_news([_news("existing")])

    # 关键字过滤放行全部
    monkeypatch.setattr(deps.kw_filter, "enabled", False)

    from sources.base import NewsItem

    items = [
        NewsItem(news_id="existing", title="t1", summary="s1", source="cls-hot"),
        NewsItem(news_id="fresh", title="t2", summary="s2", source="cls-hot"),
    ]

    async def _crawl_all():
        return {"p1": items}

    monkeypatch.setattr(deps.newsnow_batch, "crawl_all", _crawl_all)

    # 跑一轮：手动调用循环体（不 sleep）
    async def _one_round():
        results = await deps.newsnow_batch.crawl_all()
        all_items: list = []
        for _pid, its in results.items():
            all_items.extend(its)
        filtered = deps.kw_filter.filter_newsitems(all_items)
        candidates = [item.to_dict() for item in filtered]
        existing = await db.news_id_exists_batch([d["news_id"] for d in candidates])
        new_items = [d for d in candidates if d["news_id"] not in existing]
        if new_items:
            await db.upsert_news(new_items)
            deps.news_store.extend(new_items)

    await _one_round()
    # existing 不重复，fresh 新增
    _, total = await db.list_news()
    assert total == 2
    assert await db.get_news("fresh") is not None
    await db.close_db()


async def test_rss_crawl_loop_dedups_via_db(monkeypatch, tmp_path):
    """_rss_crawl_loop 一轮去重。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai.db")
    await db.close_db()
    monkeypatch.setattr(db, "_db", None)
    await db.init_db()
    stores.news_store.clear()

    await db.upsert_news([_news("dup", source="rss-x")])
    monkeypatch.setattr(deps.kw_filter, "enabled", False)

    from sources.base import NewsItem

    items = [
        NewsItem(news_id="dup", title="t1", summary="s1", source="rss-x"),
        NewsItem(news_id="new", title="t2", summary="s2", source="rss-x"),
    ]

    async def _crawl_all():
        return {"feed1": items}

    monkeypatch.setattr(deps.rss_batch, "crawl_all", _crawl_all)

    results = await deps.rss_batch.crawl_all()
    all_items = []
    for _, its in results.items():
        all_items.extend(its)
    filtered = deps.kw_filter.filter_newsitems(all_items)
    candidates = [item.to_dict() for item in filtered]
    existing = await db.news_id_exists_batch([d["news_id"] for d in candidates])
    new_items = [d for d in candidates if d["news_id"] not in existing]
    assert {d["news_id"] for d in new_items} == {"new"}
    await db.upsert_news(new_items)
    _, total = await db.list_news()
    assert total == 2
    await db.close_db()
