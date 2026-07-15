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
    """toggle 端点启动/停止调度：启动经 TaskManager 登记两个循环句柄，停止
    经 stop_background cancel 并 await 退出，避免后台跑飞。"""
    # 直接写源模块（与 app.py lifespan / toggle 端点一致），不要写 deps——
    # 写 deps 只会 shadow 在 deps.__dict__，toggle 端点写源模块后 deps 读取仍
    # 拿到 shadow 的旧值，导致跨路径不一致。
    schedule_state.schedule_running = False

    # patch 循环协程为可被 cancel 的阻塞协程（sleep 期间被 cancel 能正常退出），
    # 避免真实爬取。用 Event 持有循环使其不立即 done。
    import asyncio

    from api.tasks import task_manager

    _stop_events: list[asyncio.Event] = []

    async def _blocking_loop():
        ev = asyncio.Event()
        _stop_events.append(ev)
        try:
            await ev.wait()
        except asyncio.CancelledError:
            pass

    monkeypatch.setattr(schedule_mod, "_newsnow_crawl_loop", _blocking_loop)
    monkeypatch.setattr(schedule_mod, "_rss_crawl_loop", _blocking_loop)

    resp = client.post("/api/schedule/toggle", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["running"] is True
    # 启动后两个循环应已登记
    assert task_manager.is_running("newsnow_crawl_loop")
    assert task_manager.is_running("rss_crawl_loop")

    resp2 = client.post("/api/schedule/toggle", json={"enabled": False})
    assert resp2.status_code == 200
    assert resp2.json()["running"] is False
    # 停止后循环已 cancel 并退出，不再 running
    assert not task_manager.is_running("newsnow_crawl_loop")
    assert not task_manager.is_running("rss_crawl_loop")


async def test_schedule_toggle_idempotent_when_already_running(monkeypatch):
    """防重复升级为"循环句柄存在性判断"：循环已在跑（已登记句柄）时再启用
    不应重复派发新 task。

    直接 await toggle_schedule 协程（不走 TestClient），可在同一事件循环里
    预登记 task 并在结束后 await 清理。
    """
    import asyncio

    from api.tasks import task_manager

    schedule_state.schedule_running = True

    # 预先登记在跑的循环句柄，模拟 lifespan 已启动的情况
    async def _blocking_loop():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    pre_newsnow = asyncio.create_task(_blocking_loop())
    pre_rss = asyncio.create_task(_blocking_loop())
    task_manager.register_background("newsnow_crawl_loop", pre_newsnow)
    task_manager.register_background("rss_crawl_loop", pre_rss)
    assert task_manager.is_running("newsnow_crawl_loop")
    assert task_manager.is_running("rss_crawl_loop")

    # patch 循环协程：若被重复派发会创建新 task，记录调用次数
    spawn_count = {"n": 0}

    async def _counted_loop():
        spawn_count["n"] += 1

    monkeypatch.setattr(schedule_mod, "_newsnow_crawl_loop", _counted_loop)
    monkeypatch.setattr(schedule_mod, "_rss_crawl_loop", _counted_loop)

    req = schedule_mod.ToggleScheduleRequest(enabled=True)
    resp = await schedule_mod.toggle_schedule(req)
    assert resp["running"] is True
    # 循环已在跑，toggle 不应重复派发
    assert spawn_count["n"] == 0
    assert task_manager.is_running("newsnow_crawl_loop")
    assert task_manager.is_running("rss_crawl_loop")
    # 预登记的句柄仍是原来的（未被替换）
    assert task_manager._background_tasks["newsnow_crawl_loop"] is pre_newsnow

    # 清理：cancel 预登记 task 并 await 退出
    await task_manager.stop_background("newsnow_crawl_loop")
    await task_manager.stop_background("rss_crawl_loop")
    schedule_state.schedule_running = False


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
