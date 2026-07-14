"""Schedule runtime state.

Owns the mutable scheduling knobs and timestamps read/updated by the
crawler loops in ``api/schedule.py`` and initialized by ``app.py``
lifespan. Kept in its own module so ``deps.py`` can re-export it without
pulling in stores or crawlers.

``app.py`` writes these directly (e.g. ``schedule_state.schedule_running =
SCHEDULE_ENABLED``) rather than going through ``deps``; ``deps`` resolves
them live via its module-level ``__getattr__`` so that all consumers
reading ``deps.schedule_running`` see the value set here.
"""

from __future__ import annotations

from config import NEWSNOW_CRAWL_INTERVAL, RSS_CRAWL_INTERVAL

# ── Schedule state ────────────────────────────────────────────────────
# schedule_running 由 app.py lifespan 与 schedule 路由的 /toggle 端点改写；
# newsnow_interval / rss_interval 由 /config 端点热更新；
# last_*_crawl 由爬虫循环每次成功后写入时间戳。
schedule_running: bool = False
newsnow_interval: int = NEWSNOW_CRAWL_INTERVAL
rss_interval: int = RSS_CRAWL_INTERVAL
last_newsnow_crawl: str | None = None
last_rss_crawl: str | None = None
