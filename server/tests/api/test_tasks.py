"""api/tasks.py 测试：TaskManager CRUD + SSE 端点（通过 TestClient）。"""

from __future__ import annotations

import asyncio

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
