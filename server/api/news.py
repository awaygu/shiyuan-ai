"""News-related API routes."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query

from config import NEWS_SOURCES
from database import (
    clear_news_content_by_source,
    list_news,
    transaction,
)

from . import deps

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["news"])


async def _bg_crawl_and_save(source: str, crawler) -> None:
    # 爬取在临界区外（网络 IO 不需要串行化）。
    try:
        items = await asyncio.wait_for(crawler.crawl(), timeout=15.0)
    except TimeoutError:
        logger.warning("[refresh] %s: crawl timed out after 15s", source)
        return
    except Exception as e:
        logger.warning("[refresh] %s crawl error: %s", source, e)
        return
    # 事务外：过滤
    filtered = deps.kw_filter.filter_newsitems(items)
    candidates = [item.to_dict() for item in filtered]
    # 事务内：查重 + 写（BEGIN IMMEDIATE 串行化写事务，同连接保证查重与写原子）。
    new_items: list[dict] = []
    inserted_ids: list[str] = []
    if candidates:
        async with transaction() as db:
            placeholders = ",".join("?" for _ in candidates)
            cur = await db.execute(
                f"SELECT news_id FROM news WHERE news_id IN ({placeholders})",
                [d["news_id"] for d in candidates],
            )
            rows = await cur.fetchall()
            existing = {row["news_id"] for row in rows}
            new_items = [d for d in candidates if d["news_id"] not in existing]
            for item in new_items:
                extra_json = json.dumps(item.get("extra", {}), ensure_ascii=False)
                cur = await db.execute(
                    """
                    INSERT OR IGNORE INTO news
                        (news_id, title, summary, content, source, url, published_at, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING news_id
                    """,
                    (
                        item["news_id"],
                        item["title"],
                        item.get("summary", ""),
                        item.get("content", ""),
                        item.get("source", ""),
                        item.get("url", ""),
                        item.get("published_at", ""),
                        extra_json,
                    ),
                )
                for row in await cur.fetchall():
                    inserted_ids.append(row["news_id"])
    # 事务后锁外：只回填真正落库的条目（INSERT OR IGNORE 被忽略的不 RETURNING）。
    if inserted_ids:
        inserted_set = set(inserted_ids)
        deps.news_store.extend([d for d in new_items if d["news_id"] in inserted_set])
    logger.info("[refresh] %s done: %d total, %d new", source, len(items), len(inserted_ids))


@router.post("/news/refresh")
async def refresh_news():
    # 爬取在临界区外（网络 IO 不需要串行化）。
    results = {}
    all_raw: list = []

    try:
        newsnow_results = await deps.newsnow_batch.crawl_all()
        for platform_id, items in newsnow_results.items():
            all_raw.extend(items)
            results[f"newsnow_{platform_id}"] = {"status": "ok", "count": len(items)}
            logger.info("  ✓ NewsNow-%s: %d items", platform_id, len(items))
    except Exception as e:
        results["newsnow"] = {"status": "error", "error": str(e)}
        logger.warning("  ✗ NewsNow: %s", e)

    try:
        rss_results = await deps.rss_batch.crawl_all()
        for feed_id, items in rss_results.items():
            all_raw.extend(items)
            results[f"rss_{feed_id}"] = {"status": "ok", "count": len(items)}
            logger.info("  ✓ RSS-%s: %d items", feed_id, len(items))
    except Exception as e:
        results["rss"] = {"status": "error", "error": str(e)}
        logger.warning("  ✗ RSS: %s", e)

    # 事务外：过滤
    filtered = deps.kw_filter.filter_newsitems(all_raw)
    candidates = [item.to_dict() for item in filtered]
    # 事务内：查重 + 写（BEGIN IMMEDIATE 串行化写事务，同连接保证查重与写原子）。
    new_items: list[dict] = []
    inserted_ids: list[str] = []
    if candidates:
        async with transaction() as db:
            placeholders = ",".join("?" for _ in candidates)
            cur = await db.execute(
                f"SELECT news_id FROM news WHERE news_id IN ({placeholders})",
                [d["news_id"] for d in candidates],
            )
            rows = await cur.fetchall()
            existing = {row["news_id"] for row in rows}
            new_items = [d for d in candidates if d["news_id"] not in existing]
            for item in new_items:
                extra_json = json.dumps(item.get("extra", {}), ensure_ascii=False)
                cur = await db.execute(
                    """
                    INSERT OR IGNORE INTO news
                        (news_id, title, summary, content, source, url, published_at, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING news_id
                    """,
                    (
                        item["news_id"],
                        item["title"],
                        item.get("summary", ""),
                        item.get("content", ""),
                        item.get("source", ""),
                        item.get("url", ""),
                        item.get("published_at", ""),
                        extra_json,
                    ),
                )
                for row in await cur.fetchall():
                    inserted_ids.append(row["news_id"])
    # 事务后锁外：只回填真正落库的条目（INSERT OR IGNORE 被忽略的不 RETURNING）。
    if inserted_ids:
        inserted_set = set(inserted_ids)
        deps.news_store.extend([d for d in new_items if d["news_id"] in inserted_set])

    # total 走 DB 计数，与 /api/news 列表端点口径一致（DB 为事实来源）。
    _, total = await list_news(source=None, offset=0, limit=1)
    return {"total": total, "new": len(inserted_ids), "total_raw": len(all_raw), "results": results}


@router.get("/news")
async def get_news(
    source: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    # DB 为事实来源：列表直接走 DB 分页查询（缓存不再作为列表来源）。
    items, total = await list_news(source=source, offset=offset, limit=limit)
    return {"total": total, "offset": offset, "limit": limit, "items": items}


@router.get("/news/{news_id}/content")
async def get_news_content(news_id: str):
    item = await deps.find_news(news_id)
    if not item:
        raise HTTPException(404, f"News not found: {news_id}")

    existing_content = item.get("content", "")
    summary = item.get("summary", "")
    if existing_content and existing_content != summary and not existing_content.startswith(summary[:50]):
        return {"news_id": news_id, "content": existing_content, "cached": True}

    url = item.get("url", "")
    if not url:
        return {"news_id": news_id, "content": summary, "cached": False, "source": "summary_only"}

    source = item.get("source", "")

    if source in deps.JS_RENDERED_SOURCES:
        content = await deps.fetch_article_content_via_jina(url)
        if content:
            # 先落库（DB 事实来源），再原地更新缓存条目（item 是缓存里的共享对象）。
            await deps.update_news_content(news_id, content)
            item["content"] = content
            return {"news_id": news_id, "content": content, "cached": False, "source": "jina"}
        content = await deps.fetch_article_content(url)
        if content:
            await deps.update_news_content(news_id, content)
            item["content"] = content
            return {"news_id": news_id, "content": content, "cached": False, "source": "original"}
        return {"news_id": news_id, "content": summary, "cached": False, "source": "summary_only"}

    content = await deps.fetch_article_content(url)
    if not content:
        content = await deps.fetch_article_content_via_jina(url)
    if not content:
        return {"news_id": news_id, "content": summary, "cached": False, "source": "summary_only"}

    await deps.update_news_content(news_id, content)
    item["content"] = content
    return {"news_id": news_id, "content": content, "cached": False, "source": "original"}


@router.post("/news/refresh/{source}")
async def refresh_news_source(source: str):
    if source in deps.NEWSNOW_CRAWLERS:
        crawler = deps.NEWSNOW_CRAWLERS[source]
    elif any(feed.id == source for feed in deps.DEFAULT_RSS_FEEDS):
        feed = next(f for f in deps.DEFAULT_RSS_FEEDS if f.id == source)
        from sources.rss import RSSCrawler

        crawler = RSSCrawler(feed)
    else:
        raise HTTPException(400, f"Unknown source: {source}")

    from .tasks import task_manager

    # 经 TaskManager 登记短期后台任务：shutdown 时 await + 异常可观测
    # （done_callback 记录异常，原本被事件循环静默吞）。
    task_manager.register_short(asyncio.create_task(_bg_crawl_and_save(source, crawler)))
    return {"source": source, "status": "refreshing"}


@router.post("/news/clear-cache/{source}")
async def clear_news_content_cache(source: str):
    if source not in NEWS_SOURCES:
        raise HTTPException(400, f"Unknown source: {source}")
    # 先落库（DB 事实来源），再失效缓存中该 source 的条目（下次读取回源 DB 回填）。
    count = await clear_news_content_by_source(source)
    deps.invalidate_news(source=source)
    return {"source": source, "cleared": count}
    return {"source": source, "cleared": count}


@router.get("/sources")
async def get_sources():
    return {"sources": NEWS_SOURCES}


@router.get("/newsnow/platforms")
async def get_newsnow_platforms():
    return {"platforms": {pid: deps.PLATFORM_CONFIG[pid]["name"] for pid in deps.NEWSNOW_CRAWLERS}}


@router.post("/newsnow/refresh")
async def refresh_newsnow():
    # 爬取在临界区外（网络 IO 不需要串行化）。
    results = await deps.newsnow_batch.crawl_all()
    all_raw: list = []
    summary = {}

    for alias, items in results.items():
        all_raw.extend(items)
        summary[alias] = {"total": len(items)}
        logger.info("  ✓ %s: %d items", alias, len(items))

    # 事务外：过滤
    filtered = deps.kw_filter.filter_newsitems(all_raw)
    candidates = [item.to_dict() for item in filtered]
    # 事务内：查重 + 写（BEGIN IMMEDIATE 串行化写事务，同连接保证查重与写原子）。
    new_items: list[dict] = []
    inserted_ids: list[str] = []
    if candidates:
        async with transaction() as db:
            placeholders = ",".join("?" for _ in candidates)
            cur = await db.execute(
                f"SELECT news_id FROM news WHERE news_id IN ({placeholders})",
                [d["news_id"] for d in candidates],
            )
            rows = await cur.fetchall()
            existing = {row["news_id"] for row in rows}
            new_items = [d for d in candidates if d["news_id"] not in existing]
            for item in new_items:
                extra_json = json.dumps(item.get("extra", {}), ensure_ascii=False)
                cur = await db.execute(
                    """
                    INSERT OR IGNORE INTO news
                        (news_id, title, summary, content, source, url, published_at, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING news_id
                    """,
                    (
                        item["news_id"],
                        item["title"],
                        item.get("summary", ""),
                        item.get("content", ""),
                        item.get("source", ""),
                        item.get("url", ""),
                        item.get("published_at", ""),
                        extra_json,
                    ),
                )
                for row in await cur.fetchall():
                    inserted_ids.append(row["news_id"])
    # 事务后锁外：只回填真正落库的条目（INSERT OR IGNORE 被忽略的不 RETURNING）。
    if inserted_ids:
        inserted_set = set(inserted_ids)
        deps.news_store.extend([d for d in new_items if d["news_id"] in inserted_set])

    return {
        "total_new": len(inserted_ids),
        "total_raw": len(all_raw),
        "total_filtered": len(filtered),
        "summary": summary,
    }


@router.post("/newsnow/refresh/{platform_id}")
async def refresh_newsnow_platform(platform_id: str):
    if platform_id not in deps.NEWSNOW_CRAWLERS:
        raise HTTPException(400, f"Unknown platform: {platform_id}. Available: {list(deps.NEWSNOW_CRAWLERS.keys())}")

    crawler = deps.NEWSNOW_CRAWLERS[platform_id]
    from .tasks import task_manager

    # 经 TaskManager 登记短期后台任务：shutdown 时 await + 异常可观测。
    task_manager.register_short(asyncio.create_task(_bg_crawl_and_save(platform_id, crawler)))
    return {"platform": platform_id, "name": crawler.platform_name, "status": "refreshing"}


@router.get("/rss/feeds")
async def get_rss_feeds():
    return {
        "feeds": [
            {"id": feed.id, "name": feed.name, "url": feed.url, "enabled": feed.enabled}
            for feed in deps.DEFAULT_RSS_FEEDS
        ]
    }


@router.post("/rss/refresh")
async def refresh_rss():
    # 爬取在临界区外（网络 IO 不需要串行化）。
    results = await deps.rss_batch.crawl_all()
    all_raw: list = []
    summary = {}

    for feed_id, items in results.items():
        all_raw.extend(items)
        summary[feed_id] = {"total": len(items)}
        logger.info("  ✓ RSS %s: %d items", feed_id, len(items))

    # 事务外：过滤
    filtered = deps.kw_filter.filter_newsitems(all_raw)
    candidates = [item.to_dict() for item in filtered]
    # 事务内：查重 + 写（BEGIN IMMEDIATE 串行化写事务，同连接保证查重与写原子）。
    new_items: list[dict] = []
    inserted_ids: list[str] = []
    if candidates:
        async with transaction() as db:
            placeholders = ",".join("?" for _ in candidates)
            cur = await db.execute(
                f"SELECT news_id FROM news WHERE news_id IN ({placeholders})",
                [d["news_id"] for d in candidates],
            )
            rows = await cur.fetchall()
            existing = {row["news_id"] for row in rows}
            new_items = [d for d in candidates if d["news_id"] not in existing]
            for item in new_items:
                extra_json = json.dumps(item.get("extra", {}), ensure_ascii=False)
                cur = await db.execute(
                    """
                    INSERT OR IGNORE INTO news
                        (news_id, title, summary, content, source, url, published_at, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING news_id
                    """,
                    (
                        item["news_id"],
                        item["title"],
                        item.get("summary", ""),
                        item.get("content", ""),
                        item.get("source", ""),
                        item.get("url", ""),
                        item.get("published_at", ""),
                        extra_json,
                    ),
                )
                for row in await cur.fetchall():
                    inserted_ids.append(row["news_id"])
    # 事务后锁外：只回填真正落库的条目（INSERT OR IGNORE 被忽略的不 RETURNING）。
    if inserted_ids:
        inserted_set = set(inserted_ids)
        deps.news_store.extend([d for d in new_items if d["news_id"] in inserted_set])

    return {
        "total_new": len(inserted_ids),
        "total_raw": len(all_raw),
        "total_filtered": len(filtered),
        "summary": summary,
    }
