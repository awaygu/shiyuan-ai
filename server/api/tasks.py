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
        self.tasks: dict[str, AsyncTask] = {}
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> TaskManager:
        if cls._instance is None:
            cls._instance = TaskManager()
        return cls._instance

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
