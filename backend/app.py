"""FastAPI main entry for Zhixi - AI Interpretation & Knowledge Base system."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import (
    NEWS_SOURCES,
    SCHEDULE_ENABLED,
    NEWSNOW_CRAWL_INTERVAL,
    RSS_CRAWL_INTERVAL,
)
from database import (
    init_db,
    load_news,
    save_news,
    load_articles,
    load_publish_log,
)
from routers.deps import (
    news_store,
    article_store,
    publish_log,
    kw_filter,
    newsnow_batch,
    rss_batch,
    schedule_running as _schedule_running,
    newsnow_interval as _newsnow_interval,
    rss_interval as _rss_interval,
)
from routers.news import router as news_router
from routers.interpret import router as interpret_router
from routers.publish import router as publish_router
from routers.schedule import router as schedule_router
from routers.keywords import router as keywords_router
from routers.prompts import router as prompts_router
from routers.agent import router as agent_router
from routers.knowledge import router as knowledge_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def lifespan(app: FastAPI):
    import routers.deps as _d

    await init_db()

    persisted_news = await load_news()
    if persisted_news:
        valid_sources = set(NEWS_SOURCES.keys())
        stale = any(n.get("source") not in valid_sources for n in persisted_news)
        if stale:
            logger.info("Detected stale source format in DB, re-crawling...")
            persisted_news = None

    if persisted_news:
        _d.news_store = persisted_news
        logger.info("Loaded %d news items from DB", len(_d.news_store))
    else:
        logger.info("Crawling all sources on startup...")
        newsnow_results = await newsnow_batch.crawl_all()
        all_newsnow: list = []
        for platform_id, items in newsnow_results.items():
            all_newsnow.extend(items)
            logger.info("  ✓ NewsNow-%s: %d items", platform_id, len(items))

        rss_results = await rss_batch.crawl_all()
        all_rss: list = []
        for feed_id, items in rss_results.items():
            all_rss.extend(items)
            logger.info("  ✓ RSS-%s: %d items", feed_id, len(items))

        all_raw = all_newsnow + all_rss
        filtered = kw_filter.filter_newsitems(all_raw)
        for item in filtered:
            _d.news_store.append(item.to_dict())

        if _d.news_store:
            await save_news(_d.news_store)
        logger.info("Total news items: %d (filtered from %d)", len(_d.news_store), len(all_raw))

    _d.article_store = await load_articles()
    _d.publish_log = await load_publish_log()

    _d.schedule_running = SCHEDULE_ENABLED
    if _d.schedule_running:
        logger.info(
            "Schedule enabled: NewsNow every %ds, RSS every %ds",
            _d.newsnow_interval,
            _d.rss_interval,
        )
        from routers.schedule import _newsnow_crawl_loop, _rss_crawl_loop
        asyncio.create_task(_newsnow_crawl_loop())
        asyncio.create_task(_rss_crawl_loop())

    yield


app = FastAPI(title="智析 - AI解读与知识库", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(news_router)
app.include_router(interpret_router)
app.include_router(publish_router)
app.include_router(schedule_router)
app.include_router(keywords_router)
app.include_router(prompts_router)
app.include_router(agent_router)
app.include_router(knowledge_router)


if __name__ == "__main__":
    import uvicorn
    from config import HOST, PORT
    uvicorn.run("app:app", host=HOST, port=PORT, reload=True)
