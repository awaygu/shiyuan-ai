"""Schedule management API routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import SCHEDULE_ENABLED, SCHEDULE_MIN_INTERVAL

from . import deps

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class ToggleScheduleRequest(BaseModel):
    enabled: bool


class ScheduleConfigRequest(BaseModel):
    newsnow_interval: int | None = None
    rss_interval: int | None = None


async def _newsnow_crawl_loop():
    while deps.schedule_running:
        await asyncio.sleep(deps.newsnow_interval)
        if not deps.schedule_running:
            break
        try:
            logger.info("[Schedule] NewsNow crawl started...")
            results = await deps.newsnow_batch.crawl_all()
            all_items: list = []
            for pid, items in results.items():
                all_items.extend(items)
                logger.info("  [Schedule] NewsNow-%s: %d items", pid, len(items))
            filtered = deps.kw_filter.filter_newsitems(all_items)
            new_items: list = []
            for item in filtered:
                d = item.to_dict()
                if not any(n["news_id"] == d["news_id"] for n in deps.news_store):
                    deps.news_store.append(d)
                    new_items.append(d)
            if new_items:
                await deps.upsert_news(new_items)
                logger.info("[Schedule] NewsNow: %d new items saved (filtered from %d)", len(new_items), len(all_items))
            deps.last_newsnow_crawl = datetime.now().isoformat()
        except Exception as e:
            logger.error("[Schedule] NewsNow crawl error: %s", e)


async def _rss_crawl_loop():
    while deps.schedule_running:
        await asyncio.sleep(deps.rss_interval)
        if not deps.schedule_running:
            break
        try:
            logger.info("[Schedule] RSS crawl started...")
            results = await deps.rss_batch.crawl_all()
            all_items: list = []
            for feed_id, items in results.items():
                all_items.extend(items)
                logger.info("  [Schedule] RSS-%s: %d items", feed_id, len(items))
            filtered = deps.kw_filter.filter_newsitems(all_items)
            new_items: list = []
            for item in filtered:
                d = item.to_dict()
                if not any(n["news_id"] == d["news_id"] for n in deps.news_store):
                    deps.news_store.append(d)
                    new_items.append(d)
            if new_items:
                await deps.upsert_news(new_items)
                logger.info("[Schedule] RSS: %d new items saved (filtered from %d)", len(new_items), len(all_items))
            deps.last_rss_crawl = datetime.now().isoformat()
        except Exception as e:
            logger.error("[Schedule] RSS crawl error: %s", e)


@router.get("/status")
async def get_schedule_status():
    return {
        "enabled": SCHEDULE_ENABLED,
        "running": deps.schedule_running,
        "newsnow_interval": deps.newsnow_interval,
        "rss_interval": deps.rss_interval,
        "last_newsnow_crawl": deps.last_newsnow_crawl,
        "last_rss_crawl": deps.last_rss_crawl,
    }


@router.post("/toggle")
async def toggle_schedule(req: ToggleScheduleRequest):
    if req.enabled and not deps.schedule_running:
        deps.schedule_running = True
        asyncio.create_task(_newsnow_crawl_loop())
        asyncio.create_task(_rss_crawl_loop())
        logger.info("Schedule started by API")
    elif not req.enabled and deps.schedule_running:
        deps.schedule_running = False
        logger.info("Schedule stopped by API")
    return {
        "running": deps.schedule_running,
        "newsnow_interval": deps.newsnow_interval,
        "rss_interval": deps.rss_interval,
    }


@router.post("/config")
async def update_schedule_config(req: ScheduleConfigRequest):
    if req.newsnow_interval is not None:
        if req.newsnow_interval < SCHEDULE_MIN_INTERVAL:
            raise HTTPException(
                400,
                f"newsnow_interval must be >= {SCHEDULE_MIN_INTERVAL}s",
            )
        deps.newsnow_interval = req.newsnow_interval
        logger.info("NewsNow interval updated to %ds", deps.newsnow_interval)
    if req.rss_interval is not None:
        if req.rss_interval < SCHEDULE_MIN_INTERVAL:
            raise HTTPException(
                400,
                f"rss_interval must be >= {SCHEDULE_MIN_INTERVAL}s",
            )
        deps.rss_interval = req.rss_interval
        logger.info("RSS interval updated to %ds", deps.rss_interval)
    return {
        "newsnow_interval": deps.newsnow_interval,
        "rss_interval": deps.rss_interval,
    }
