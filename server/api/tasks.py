"""Async task management with SSE progress streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tasks"])


@dataclass
class AsyncTask:
    task_id: str
    task_type: str
    platform: str
    title: str
    status: str = "pending"
    progress: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    result: dict | None = None
    error: str | None = None
    need_login: bool = False

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "platform": self.platform,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
            "need_login": self.need_login,
        }


class TaskManager:
    _instance: TaskManager | None = None

    def __init__(self):
        # 发布任务元数据（面向用户的进度/SSE），不持有 asyncio.Task 句柄。
        self.tasks: dict[str, AsyncTask] = {}
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()
        # 长跑循环句柄：按 name 去重（如 "newsnow_crawl_loop"）。
        # 用于 lifespan/toggle 两条启动路径统一防重复派发，shutdown 时 cancel + await。
        self._background_tasks: dict[str, asyncio.Task] = {}
        # 短期后台任务句柄（手动爬取 _bg_crawl_and_save、发布任务等）：
        # 主要是为了 shutdown 时能 await + 异常可观测。done 后自动从集合移除。
        self._short_tasks: set[asyncio.Task] = set()

    @classmethod
    def get(cls) -> TaskManager:
        if cls._instance is None:
            cls._instance = TaskManager()
        return cls._instance

    # ── 长跑循环管理 ──────────────────────────────────────────────────

    def register_background(self, name: str, task: asyncio.Task) -> bool:
        """登记长跑循环句柄，按 name 去重。

        返回 True 表示已登记新循环；False 表示同名循环已在跑，新 task 被
        取消（避免重复派发）。供 lifespan/toggle 统一防重复。
        """
        existing = self._background_tasks.get(name)
        if existing is not None and not existing.done():
            # 同名循环仍在跑：取消新派发的 task，保留已在跑的。
            task.cancel()
            logger.warning("[TaskManager] %s 已在运行，取消重复派发的 task", name)
            return False
        self._background_tasks[name] = task
        task.add_done_callback(lambda t, n=name: self._background_tasks.pop(n, None))
        return True

    def is_running(self, name: str) -> bool:
        """查某长跑循环是否在跑（句柄存在且未完成）。"""
        task = self._background_tasks.get(name)
        return task is not None and not task.done()

    async def stop_background(self, name: str) -> None:
        """cancel 指定长跑循环并 await 其退出。"""
        task = self._background_tasks.pop(name, None)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001 - 退出时记录异常即可
            logger.error("[TaskManager] %s 退出时异常: %s", name, e)

    # ── 短期后台任务管理 ──────────────────────────────────────────────

    def register_short(self, task: asyncio.Task) -> None:
        """登记短期后台 task 句柄（手动爬取/发布等）。

        done 后自动从集合移除；若 task 因异常结束则记录日志（当前异常会被
        事件循环静默吞，这里补可观测性）。
        """

        def _on_done(t: asyncio.Task) -> None:
            self._short_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error("[TaskManager] 短期后台任务异常: %s", exc, exc_info=exc)

        self._short_tasks.add(task)
        task.add_done_callback(_on_done)

    # ── 统一关闭 ──────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """关闭所有后台任务：置 schedule_running=False + cancel 长跑循环 +
        await 全部完成（含短期任务）。

        lifespan shutdown 在 close_db 前调用，避免后台 DB 写入被切断。
        """
        # 先置标志位，让 while deps.schedule_running 循环自然退出。
        try:
            from . import schedule_state as _sch

            _sch.schedule_running = False
        except Exception:  # noqa: BLE001
            logger.debug("[TaskManager] shutdown 置 schedule_running=False 失败", exc_info=True)

        # cancel 并 await 长跑循环
        bg_tasks = list(self._background_tasks.values())
        for task in bg_tasks:
            if not task.done():
                task.cancel()
        if bg_tasks:
            await asyncio.gather(*bg_tasks, return_exceptions=True)
        self._background_tasks.clear()

        # await 短期任务（不 cancel，让其自然完成；DB 写入途中不应被中断）
        short_tasks = list(self._short_tasks)
        if short_tasks:
            await asyncio.gather(*short_tasks, return_exceptions=True)
        self._short_tasks.clear()

    async def create_task(
        self,
        task_type: str,
        platform: str,
        title: str,
    ) -> AsyncTask:
        task_id = uuid.uuid4().hex[:12]
        task = AsyncTask(
            task_id=task_id,
            task_type=task_type,
            platform=platform,
            title=title,
        )
        async with self._lock:
            self.tasks[task_id] = task
        await self._broadcast(task)
        return task

    async def update_task(
        self,
        task_id: str,
        status: str | None = None,
        progress: str | None = None,
        result: dict | None = None,
        error: str | None = None,
        need_login: bool | None = None,
    ):
        task = self.tasks.get(task_id)
        if not task:
            return
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress = progress
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        if need_login is not None:
            task.need_login = need_login
        task.updated_at = datetime.now().isoformat()
        await self._broadcast(task)

    def get_all_tasks(self) -> list[AsyncTask]:
        return sorted(
            self.tasks.values(),
            key=lambda t: t.created_at,
            reverse=True,
        )

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue):
        async with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    async def _broadcast(self, task: AsyncTask):
        data = json.dumps(
            {"type": "task_update", **task.to_dict()},
            ensure_ascii=False,
        )
        async with self._lock:
            dead: list[asyncio.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    pass
                except Exception:
                    dead.append(q)
            for q in dead:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass

    async def clear_done(self):
        async with self._lock:
            to_remove = [tid for tid, t in self.tasks.items() if t.status in ("completed", "failed")]
            for tid in to_remove:
                del self.tasks[tid]


task_manager = TaskManager.get()


@router.get("/tasks")
async def get_tasks():
    return {"tasks": [t.to_dict() for t in task_manager.get_all_tasks()]}


@router.delete("/tasks")
async def clear_tasks():
    await task_manager.clear_done()
    return {"tasks": [t.to_dict() for t in task_manager.get_all_tasks()]}


@router.get("/tasks/stream")
async def stream_tasks():
    from .deps import SSE_HEADERS

    q = await task_manager.subscribe()

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await task_manager.unsubscribe(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
