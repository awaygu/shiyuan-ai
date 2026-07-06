"""Publish and article management API routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from publishers import BrowserPublisher, DouyinPublisher, WechatMpPublisher, XiaohongshuPublisher
from publishers.wechat_mp import WECHAT_IP_WHITELIST_ERROR, WechatApiError

from . import deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["publish"])

_running_publish_tasks: set[asyncio.Task] = set()
_publish_locks: dict[str, asyncio.Lock] = {}


def _get_lock(platform: str) -> asyncio.Lock:
    if platform not in _publish_locks:
        _publish_locks[platform] = asyncio.Lock()
    return _publish_locks[platform]


def _init_publishers():
    from config import WECHAT_APP_ID, WECHAT_APP_SECRET

    wechat = WechatMpPublisher(app_id=WECHAT_APP_ID, app_secret=WECHAT_APP_SECRET)
    xiaohongshu = XiaohongshuPublisher()
    douyin = DouyinPublisher()

    deps.PUBLISHERS = {
        "xiaohongshu": xiaohongshu,
        "wechat_mp": wechat,
        "douyin": douyin,
    }


_init_publishers()


class PublishRequest(BaseModel):
    article_id: str | None = None
    title: str | None = None
    content: str | None = None
    platform: str
    generate_cover: bool = True
    generate_inline_images: bool = False


@router.post("/publish")
async def publish_article(req: PublishRequest):
    from .tasks import task_manager

    publisher = deps.PUBLISHERS.get(req.platform)
    if not publisher:
        raise HTTPException(
            400,
            f"Unknown platform: {req.platform}. Available: {list(deps.PUBLISHERS.keys())}",
        )

    title = req.title
    content = req.content

    if req.article_id and (not title or not content):
        article = deps.find_article(req.article_id)
        if not article:
            raise HTTPException(404, f"Article not found: {req.article_id}")
        title = title or article.get("title", "")
        content = content or article.get("content", "")

    if not title or not content:
        raise HTTPException(400, "title and content are required (either directly or via article_id)")

    clean_title = title[:40] if title else "文章"
    task = await task_manager.create_task("publish", req.platform, clean_title)

    task_ref = asyncio.create_task(
        _safe_run_publish_task(
            task=task,
            publisher=publisher,
            title=title,
            content=content,
            article_id=req.article_id or "",
            generate_cover=req.generate_cover,
            generate_inline_images=req.generate_inline_images,
        )
    )
    _running_publish_tasks.add(task_ref)
    task_ref.add_done_callback(_running_publish_tasks.discard)

    return {"task_id": task.task_id, "status": "pending"}


async def _safe_run_publish_task(*args, **kwargs):
    """Wrap _run_publish_task to catch initialization/setup errors."""
    from .tasks import task_manager

    task = kwargs.get("task") or args[0]
    try:
        await _run_publish_task(*args, **kwargs)
    except Exception as e:
        logger.exception("Publish task %s failed before completion", task.task_id)
        await task_manager.update_task(
            task.task_id,
            "failed",
            f"发布任务初始化失败：{e}",
            error=str(e),
        )


async def _run_publish_task(
    task,
    publisher,
    title: str,
    content: str,
    article_id: str,
    generate_cover: bool,
    generate_inline_images: bool,
):
    from .tasks import task_manager

    async def on_progress(msg: str):
        await task_manager.update_task(task.task_id, "running", msg)

    await task_manager.update_task(task.task_id, "running", "正在发布...")

    try:
        result = await publisher.publish(
            title,
            content,
            generate_cover=generate_cover,
            generate_inline_images=generate_inline_images,
            on_progress=on_progress,
        )
    except Exception as e:
        logger.error("Publish error for %s: %s", task.platform, e)
        from publishers.base import PublishResult

        result = PublishResult(
            success=False,
            platform=task.platform,
            article_title=title,
            error_message=str(e),
        )

    record = {
        "article_id": article_id,
        "platform": task.platform,
        "success": result.success,
        "url": result.published_url,
        "timestamp": result.published_at.isoformat(),
        "need_login": result.need_login,
        "error_message": result.error_message,
        "extra": result.extra,
    }

    async with deps.article_lock:
        deps.publish_log.append(record)
        await deps.save_publish_record(record)

    if result.success:
        await task_manager.update_task(
            task.task_id,
            "completed",
            result.error_message or "发布成功",
            result=record,
        )
    else:
        await task_manager.update_task(
            task.task_id,
            "failed",
            result.error_message or "发布失败",
            result=record,
            error=result.error_message,
            need_login=result.need_login,
        )


@router.post("/publish/{platform}/login")
async def login_platform(platform: str):
    publisher = deps.PUBLISHERS.get(platform)
    if not publisher:
        raise HTTPException(400, f"Unknown platform: {platform}")

    lock = _get_lock(platform)
    if lock.locked():
        raise HTTPException(429, f"A task is already running for {platform}")

    error_message = ""
    login_exc = None
    async with lock:
        try:
            success = await publisher.do_login()
        except Exception as e:
            success = False
            error_message = str(e)
            login_exc = e

    if not success:
        if isinstance(publisher, WechatMpPublisher):
            if isinstance(login_exc, WechatApiError) and login_exc.errcode == WECHAT_IP_WHITELIST_ERROR:
                error_message = "服务器IP不在微信白名单，请在微信公众平台 → 开发 → 基本配置中添加IP白名单"
            elif not publisher.app_id or not publisher.app_secret:
                error_message = error_message or "未配置 WECHAT_APP_ID 或 WECHAT_APP_SECRET，请在 .env 中设置"
            else:
                error_message = error_message or "access_token 获取失败，请检查 AppID 和 AppSecret 是否正确"
        elif isinstance(publisher, BrowserPublisher) and publisher._last_login_error:
            error_message = publisher._last_login_error
        else:
            error_message = error_message or "登录失败或超时，请重试"

    return {"success": success, "platform": platform, "error_message": error_message}


@router.get("/publish/{platform}/status")
async def login_status(platform: str):
    publisher = deps.PUBLISHERS.get(platform)
    if not publisher:
        raise HTTPException(400, f"Unknown platform: {platform}")

    error_message = ""
    status_exc = None
    try:
        logged_in = await publisher.check_login()
    except Exception as e:
        logged_in = False
        error_message = str(e)
        status_exc = e

    if not logged_in and not error_message:
        if isinstance(publisher, WechatMpPublisher):
            if isinstance(status_exc, WechatApiError) and status_exc.errcode == WECHAT_IP_WHITELIST_ERROR:
                error_message = "服务器IP不在微信白名单，请在公众平台 → 开发 → 基本配置中添加IP白名单"
            elif not publisher.app_id or not publisher.app_secret:
                error_message = "未配置 WECHAT_APP_ID 或 WECHAT_APP_SECRET"
            else:
                error_message = "access_token 无效，请检查配置"
        elif isinstance(publisher, BrowserPublisher):
            error_message = "Cookies 不存在或已过期，请重新扫码登录"

    return {"logged_in": logged_in, "platform": platform, "error_message": error_message}


@router.get("/publish_log")
async def get_publish_log(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    sorted_log = sorted(deps.publish_log, key=lambda r: r.get("timestamp", ""), reverse=True)
    total = len(sorted_log)
    return {"total": total, "offset": offset, "limit": limit, "items": sorted_log[offset : offset + limit]}


@router.get("/articles")
async def get_articles(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    sorted_articles = sorted(deps.article_store, key=lambda a: a.get("article_id", ""), reverse=True)
    total = len(sorted_articles)
    return {"total": total, "offset": offset, "limit": limit, "items": sorted_articles[offset : offset + limit]}
