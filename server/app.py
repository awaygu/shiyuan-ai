"""FastAPI main entry for shiyuan - AI Interpretation & Knowledge Base system."""

from __future__ import annotations

import asyncio
import logging
import sys

if sys.platform == "win32" and sys.version_info < (3, 13):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.agent import router as agent_router
from api.conversations import router as conversations_router
from api.deps import (
    kw_filter,
    newsnow_batch,
    rss_batch,
)
from api.errors import register_exception_handlers
from api.interpret import router as interpret_router
from api.keywords import router as keywords_router
from api.knowledge import router as knowledge_router
from api.news import router as news_router
from api.prompts import router as prompts_router
from api.publish import router as publish_router
from api.schedule import router as schedule_router
from api.tasks import router as tasks_router
from config import (
    CORS_ORIGINS,
    NEWS_SOURCES,
    NEWSNOW_API_URL,
    SCHEDULE_ENABLED,
)
from database import (
    close_db,
    delete_all_news,
    get_news_sources,
    init_db,
    load_news,
    upsert_news,
)
from sources.newsnow import FALLBACK_API_URL, check_newsnow_health

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

NEWSNOW_WAIT_TIMEOUT = 10
NEWSNOW_WAIT_INTERVAL = 1


async def _wait_for_newsnow():
    base_url = NEWSNOW_API_URL
    logger.info("Checking NewsNow availability at %s ...", base_url)
    elapsed = 0
    while elapsed < NEWSNOW_WAIT_TIMEOUT:
        if await check_newsnow_health(base_url):
            logger.info("NewsNow is ready (%.1fs)", elapsed)
            return
        logger.debug("NewsNow not ready, waiting %.1fs ...", NEWSNOW_WAIT_INTERVAL)
        await asyncio.sleep(NEWSNOW_WAIT_INTERVAL)
        elapsed += NEWSNOW_WAIT_INTERVAL
    logger.warning(
        "NewsNow not ready after %ds, will use fallback: %s",
        NEWSNOW_WAIT_TIMEOUT,
        FALLBACK_API_URL,
    )


async def lifespan(app: FastAPI):
    # 直接对源模块（schedule_state / stores）赋值，而不是对 deps 赋值：
    # deps 已将 schedule_running / news_store 等改为通过 __getattr__ 实时转发到
    # 源模块，若 `_d.schedule_running = X` 只会改 deps 命名空间，不会更新源模块。
    #
    # 缓存策略：DB 是唯一事实来源。
    # - news_store：启动时从 DB 预热（供 trends/search/briefing 等全量扫描端点
    #   使用，避免重启后返回"无数据"）；运行时写先落库再 invalidate/extend 缓存。
    # - article_store / publish_log：不预热。列表端点直接读 DB，find_article
    #   读缓存未命中回源 DB 回填。
    import api.schedule_state as _sch
    import api.stores as _s

    await _wait_for_newsnow()

    await init_db()

    # 初始化记忆数据库
    from config import MEMORY_DB_PATH
    from core.checkpointer import init_db as init_memory_db

    init_memory_db(MEMORY_DB_PATH)

    # 过期 source 检测：DB 为事实来源，查 DISTINCT source 判断是否存在失效格式。
    # 若检测到过期 source，清空 DB 后重新爬取（避免过期记录残留）。
    valid_sources = set(NEWS_SOURCES.keys())
    db_sources = await get_news_sources()
    stale = bool(db_sources) and any(src not in valid_sources for src in db_sources)

    if stale:
        logger.info("Detected stale source format in DB, re-crawling...")
        await delete_all_news()

    if stale or not db_sources:
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
        new_items = [item.to_dict() for item in filtered]
        # 增量入库：已存在的 news_id 跳过，避免全量 DELETE+INSERT。
        if new_items:
            await upsert_news(new_items)

        logger.info("Total news items saved: %d (filtered from %d)", len(new_items), len(all_raw))
    else:
        logger.info("News already persisted in DB (%d sources), skipping startup crawl", len(db_sources))

    # 预热 news_store 缓存：trends/search/briefing 等全量扫描端点直接读缓存，
    # 不预热会导致重启后返回"无数据"。DB 仍是事实来源，缓存仅作读加速。
    _s.news_store = await load_news()
    logger.info("Preloaded news cache: %d items", len(_s.news_store))

    _sch.schedule_running = SCHEDULE_ENABLED
    if _sch.schedule_running:
        logger.info(
            "Schedule enabled: NewsNow every %ds, RSS every %ds",
            _sch.newsnow_interval,
            _sch.rss_interval,
        )
        from api.schedule import _newsnow_crawl_loop, _rss_crawl_loop
        from api.tasks import task_manager

        # 经 TaskManager 登记长跑循环句柄：register_background 内按 name 去重，
        # shutdown 时可 cancel + await，避免后台循环在 close_db 后仍跑飞。
        task_manager.register_background(
            "newsnow_crawl_loop",
            asyncio.create_task(_newsnow_crawl_loop()),
        )
        task_manager.register_background(
            "rss_crawl_loop",
            asyncio.create_task(_rss_crawl_loop()),
        )

    yield

    # 关闭：先停后台任务（置 schedule_running=False + cancel 循环 + await 全部
    # 完成，含短期任务），再关 DB。避免后台 DB 写入途中被切断。
    from api.tasks import task_manager

    await task_manager.shutdown()
    await close_db()


app = FastAPI(title="识渊 - AI解读与知识库", version="1.0.0", lifespan=lifespan)

# 全局 exception_handler：统一普通 JSON 端点的错误响应格式（envelope 保留
# detail 兼容 + code/type 扩展）。必须在 middleware 前注册。注意：lifespan
# 内异常与 SSE 端点内异常不走全局 handler，仅覆盖普通 JSON 端点。
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS.split(",") if CORS_ORIGINS != "*" else ["*"],
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
app.include_router(tasks_router)
app.include_router(conversations_router)


if __name__ == "__main__":
    import uvicorn

    from config import HOST, PORT

    uvicorn.run("app:app", host=HOST, port=PORT, reload=True, loop="asyncio")
