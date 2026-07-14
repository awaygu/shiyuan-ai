"""Crawler registry and batch crawler instances.

Builds the per-platform ``NewsNowCrawler`` registry and the shared
``NewsNowBatchCrawler`` / ``RSSBatchCrawler`` instances used by the news
refresh endpoints and the schedule crawler loops.

Only depends on ``sources`` (NewsNow + RSS). The keyword filter that
filters crawler output lives in ``singletons.py``; callers fetch it via
``deps.kw_filter``.
"""

from __future__ import annotations

from sources import (
    DEFAULT_RSS_FEEDS,
    PLATFORM_CONFIG,
    NewsNowBatchCrawler,
    NewsNowCrawler,
    RSSBatchCrawler,
)

# ── Crawler registry ─────────────────────────────────────────────────
# 为 PLATFORM_CONFIG 中每个平台实例化一个 NewsNowCrawler；平台 id 在
# NewsNowCrawler.__init__ 内未命中时抛 ValueError，这里静默跳过，避免某个
# 平台配置异常导致整组爬虫不可用。
NEWSNOW_CRAWLERS: dict[str, NewsNowCrawler] = {}
for platform_id in PLATFORM_CONFIG:
    try:
        NEWSNOW_CRAWLERS[platform_id] = NewsNowCrawler(platform_id)
    except ValueError:
        pass

# 共享的批量爬虫实例：newsnow_batch 覆盖所有平台，rss_batch 覆盖启用的 RSS 源。
# crawl_all() 被 news 刷新端点、schedule 循环、agent 工具共同调用。
newsnow_batch = NewsNowBatchCrawler()
rss_batch = RSSBatchCrawler(DEFAULT_RSS_FEEDS)
