"""Publish and article management API routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database import list_articles, list_publish_log, save_publish_record
from publishers import BrowserPublisher, DouyinPublisher, WechatMpPublisher, XiaohongshuPublisher
from publishers.wechat_mp import WECHAT_IP_WHITELIST_ERROR, WechatApiError

from . import deps
from .errors import bad_request, not_found, unknown_platform

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["publish"])

_publish_locks: dict[str, asyncio.Lock] = {}


def _get_lock(platform: str) -> asyncio.Lock:
    if platform not in _publish_locks:
        _publish_locks[platform] = asyncio.Lock()
    return _publish_locks[platform]


def _already_running(platform: str) -> HTTPException:
    """构造 429 并发冲突异常（带 Retry-After 提示客户端稍后重试）。

    errors.py 没有提供 429 helper（发布并发守卫是 publish 路由特有语义），
    故在本地构造 HTTPException；统一信封由 app.py 注册的全局
    exception_handler 自动加 code/type，headers 也一并透传。
    """
    return HTTPException(
        status_code=429,
        detail=f"A task is already running for {platform}",
        headers={"Retry-After": "5"},
    )


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
        raise unknown_platform(req.platform, available=list(deps.PUBLISHERS.keys()))

    title = req.title
    content = req.content

    if req.article_id and (not title or not content):
        article = await deps.find_article(req.article_id)
        if not article:
            raise not_found(f"Article not found: {req.article_id}")
        title = title or article.get("title", "")
        content = content or article.get("content", "")

    if not title or not content:
        raise bad_request("title and content are required (either directly or via article_id)")

    clean_title = title[:40] if title else "文章"
    task = await task_manager.create_task("publish", req.platform, clean_title)

    # 经 TaskManager 登记发布任务句柄：统一收口，shutdown 时可 await
    # （_safe_run_publish_task 已捕获异常并标记失败，register_short 的
    # done_callback 不会重复记录已处理的异常）。
    task_manager.register_short(
        asyncio.create_task(
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
    )

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

    # publish_log 写走纯 DB：save_publish_record 是单条 INSERT，SQLite WAL 下并发安全，
    # 不再借用 article_lock。先落库（事实来源），再失效缓存。
    await save_publish_record(record)
    deps.invalidate_publish_log()

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
        raise unknown_platform(platform, available=list(deps.PUBLISHERS.keys()))

    lock = _get_lock(platform)
    # 单 asyncio 事件循环下，locked() 检查与下方 `async with lock` 之间无 await，
    # 不构成 TOCTOU；此快速检查仅用于乐观早退返回 429，真正互斥仍由 `async with lock` 保证。
    if lock.locked():
        raise _already_running(platform)

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
        raise unknown_platform(platform, available=list(deps.PUBLISHERS.keys()))

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
    # DB 为事实来源：列表直接走 DB 分页查询（ORDER BY id DESC）。
    items, total = await list_publish_log(offset=offset, limit=limit)
    return {"total": total, "offset": offset, "limit": limit, "items": items}


@router.get("/articles")
async def get_articles(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    # DB 为事实来源：列表直接走 DB 分页查询（ORDER BY created_at DESC，
    # 替代原内存版按 article_id 排序，统一为时间倒序）。
    items, total = await list_articles(offset=offset, limit=limit)
    return {"total": total, "offset": offset, "limit": limit, "items": items}
