"""api/tasks.py 测试：TaskManager CRUD + SSE 端点（通过 TestClient）。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api.tasks import AsyncTask, TaskManager


def test_async_task_to_dict_contains_all_fields():
    task = AsyncTask(task_id="t1", task_type="publish", platform="xiaohongshu", title="标题")
    d = task.to_dict()
    assert d["task_id"] == "t1"
    assert d["task_type"] == "publish"
    assert d["platform"] == "xiaohongshu"
    assert d["title"] == "标题"
    assert d["status"] == "pending"
    assert "created_at" in d
    assert "updated_at" in d
    assert d["result"] is None
    assert d["error"] is None
    assert d["need_login"] is False


async def test_task_manager_create_and_update():
    """TaskManager.create_task / update_task 修改字段并广播。"""
    mgr = TaskManager()
    mgr.tasks.clear()
    mgr._subscribers.clear()
    task = await mgr.create_task("publish", "xiaohongshu", "标题")
    assert task.task_id in mgr.tasks

    await mgr.update_task(
        task.task_id,
        status="running",
        progress="正在发布",
        result={"url": "x"},
        need_login=False,
    )
    updated = mgr.tasks[task.task_id]
    assert updated.status == "running"
    assert updated.progress == "正在发布"
    assert updated.result == {"url": "x"}


async def test_task_manager_update_unknown_task_noop():
    """update_task 对未知 task_id 安全返回。"""
    mgr = TaskManager()
    mgr.tasks.clear()
    mgr._subscribers.clear()
    await mgr.update_task("nonexistent", status="running")  # 不应抛错


async def test_task_manager_get_all_tasks_sorted_desc_by_created_at():
    """get_all_tasks 按 created_at DESC 排序。created_at 秒级精度，快速创建可能相同，
    故显式设置不同时间戳以稳定验证排序方向。"""
    mgr = TaskManager()
    mgr.tasks.clear()
    mgr._subscribers.clear()
    t1 = await mgr.create_task("a", "p1", "title1")
    t2 = await mgr.create_task("b", "p2", "title2")
    # 显式赋予递增时间戳
    t1.created_at = "2024-01-01T00:00:00"
    t2.created_at = "2024-06-01T00:00:00"
    all_tasks = mgr.get_all_tasks()
    # DESC：t2（更新）排前
    assert all_tasks[0].task_id == t2.task_id
    assert all_tasks[-1].task_id == t1.task_id


async def test_task_manager_subscribe_unsubscribe():
    mgr = TaskManager()
    mgr._subscribers.clear()
    q = await mgr.subscribe()
    assert q in mgr._subscribers
    await mgr.unsubscribe(q)
    assert q not in mgr._subscribers


async def test_task_manager_unsubscribe_unknown_queue_noop():
    mgr = TaskManager()
    mgr._subscribers.clear()
    q = asyncio.Queue()
    # 未订阅的 queue，unsubscribe 不应抛错
    await mgr.unsubscribe(q)


async def test_task_manager_clear_done_removes_completed_and_failed():
    mgr = TaskManager()
    mgr.tasks.clear()
    mgr._subscribers.clear()
    t1 = await mgr.create_task("a", "p", "t1")
    t2 = await mgr.create_task("b", "p", "t2")
    t3 = await mgr.create_task("c", "p", "t3")
    await mgr.update_task(t1.task_id, status="completed")
    await mgr.update_task(t2.task_id, status="failed")
    # t3 仍 pending
    await mgr.clear_done()
    assert t1.task_id not in mgr.tasks
    assert t2.task_id not in mgr.tasks
    assert t3.task_id in mgr.tasks


async def test_task_manager_broadcast_to_subscribers():
    """create_task 应向订阅者推送 task_update 事件。"""
    mgr = TaskManager()
    mgr.tasks.clear()
    mgr._subscribers.clear()
    q = await mgr.subscribe()
    task = await mgr.create_task("publish", "p", "t")
    data = await asyncio.wait_for(q.get(), timeout=1.0)
    assert "task_update" in data
    assert task.task_id in data


async def test_task_manager_get_singleton():
    """TaskManager.get 返回同一单例。"""
    TaskManager._instance = None
    a = TaskManager.get()
    b = TaskManager.get()
    assert a is b


# ── 长跑循环 / 短期任务 / shutdown ──


async def test_register_background_dedups_by_name():
    """同名循环已登记且未完成时，再次 register 应取消新 task 且不替换已登记的。"""
    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    async def _block():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    first = asyncio.create_task(_block())
    assert mgr.register_background("newsnow_crawl_loop", first) is True
    # 同名再登记：新 task 应被 cancel，返回 False，原句柄不变
    dup = asyncio.create_task(_block())
    assert mgr.register_background("newsnow_crawl_loop", dup) is False
    assert mgr._background_tasks["newsnow_crawl_loop"] is first
    # dup 被 cancel
    with pytest.raises(asyncio.CancelledError):
        await dup

    await mgr.stop_background("newsnow_crawl_loop")
    mgr._background_tasks.clear()


async def test_register_background_replaces_done_task():
    """同名旧 task 已完成时，register 应登记新 task（允许重启）。"""
    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    async def _quick():
        return None

    old = asyncio.create_task(_quick())
    await old  # 让其完成
    mgr._background_tasks["rss_crawl_loop"] = old

    async def _block():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    new = asyncio.create_task(_block())
    assert mgr.register_background("rss_crawl_loop", new) is True
    assert mgr._background_tasks["rss_crawl_loop"] is new

    await mgr.stop_background("rss_crawl_loop")
    mgr._background_tasks.clear()


async def test_is_running_reflects_state():
    """is_running 对在跑/已完成/未登记分别返回 True/False/False。"""
    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    assert mgr.is_running("newsnow_crawl_loop") is False  # 未登记

    async def _block():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(_block())
    mgr.register_background("newsnow_crawl_loop", task)
    assert mgr.is_running("newsnow_crawl_loop") is True

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    # done_callback 已从字典移除
    assert "newsnow_crawl_loop" not in mgr._background_tasks
    assert mgr.is_running("newsnow_crawl_loop") is False


async def test_stop_background_cancels_and_awaits():
    """stop_background cancel 指定循环并 await 退出，结束后不在 running。"""
    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    finished = asyncio.Event()

    async def _block():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            finished.set()

    task = asyncio.create_task(_block())
    mgr.register_background("rss_crawl_loop", task)
    # 让 task 先跑到 await 点（否则 cancel 会在 task 启动前生效，
    # 内部 except 无机会执行）。生产中循环已 sleep，cancel 能正常命中。
    await asyncio.sleep(0)
    await mgr.stop_background("rss_crawl_loop")
    assert task.done()
    assert finished.is_set()
    assert "rss_crawl_loop" not in mgr._background_tasks


async def test_stop_background_unknown_name_noop():
    """stop_background 对未登记的 name 安全返回。"""
    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()
    await mgr.stop_background("nonexistent")  # 不应抛错


async def test_register_short_records_exception(caplog):
    """register_short 的 done_callback 在 task 异常结束时应记录 error 日志。"""
    import logging

    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    async def _boom():
        raise RuntimeError("bg boom")

    task = asyncio.create_task(_boom())
    mgr.register_short(task)
    assert task in mgr._short_tasks
    # 让 task 完成，触发 done_callback
    await asyncio.gather(task, return_exceptions=True)
    # done_callback 已从集合移除
    assert task not in mgr._short_tasks
    # 异常被 logger.error 记录
    assert any("短期后台任务异常" in r.getMessage() and r.levelno == logging.ERROR for r in caplog.records)


async def test_register_short_discards_done_without_exc():
    """register_short 的 task 正常完成时应从集合移除，且不记录异常。"""
    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    async def _ok():
        return 42

    task = asyncio.create_task(_ok())
    mgr.register_short(task)
    await asyncio.gather(task, return_exceptions=True)
    assert task not in mgr._short_tasks


async def test_shutdown_cancels_loops_and_awaits_short(monkeypatch):
    """shutdown 置 schedule_running=False + cancel 长跑循环 + await 短期任务。"""
    import api.schedule_state as _sch

    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    _sch.schedule_running = True

    loop_cancelled = asyncio.Event()
    short_completed = asyncio.Event()

    async def _bg_loop():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            loop_cancelled.set()

    async def _short():
        await asyncio.sleep(0.01)  # 短期任务，很快完成
        short_completed.set()

    bg_task = asyncio.create_task(_bg_loop())
    mgr.register_background("newsnow_crawl_loop", bg_task)
    short_task = asyncio.create_task(_short())
    mgr.register_short(short_task)
    # 让 bg_loop 先跑到 await 点（否则 cancel 在启动前生效，except 无机会执行）
    await asyncio.sleep(0)

    await mgr.shutdown()
    # 标志位已置 False
    assert _sch.schedule_running is False
    # 长跑循环被 cancel
    assert loop_cancelled.is_set()
    # 短期任务被 await 完成（非 cancel）
    assert short_completed.is_set()
    assert bg_task.done()
    assert short_task.done()
    # 字典已清空
    assert mgr._background_tasks == {}
    assert mgr._short_tasks == set()
    _sch.schedule_running = False


async def test_shutdown_sets_schedule_running_false_even_without_loops():
    """无后台任务时 shutdown 仍应置 schedule_running=False。"""
    import api.schedule_state as _sch

    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    _sch.schedule_running = True
    await mgr.shutdown()
    assert _sch.schedule_running is False


async def test_shutdown_awaits_short_task_return_exceptions():
    """shutdown 对短期任务的异常用 gather(return_exceptions) 吞掉，不抛出。"""
    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    async def _boom():
        raise RuntimeError("short boom")

    short_task = asyncio.create_task(_boom())
    mgr.register_short(short_task)
    # shutdown 不应抛出（异常被 return_exceptions 吞）
    await mgr.shutdown()
    assert short_task.done()


# ── 端点 ──


def test_get_tasks_endpoint_empty(client: TestClient):
    # 重置单例以避免跨测试污染
    TaskManager._instance = None
    from api.tasks import task_manager

    task_manager.tasks.clear()
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    assert resp.json() == {"tasks": []}


def test_clear_tasks_endpoint(client: TestClient):
    TaskManager._instance = None
    from api.tasks import task_manager

    task_manager.tasks.clear()
    resp = client.delete("/api/tasks")
    assert resp.status_code == 200
    assert "tasks" in resp.json()
