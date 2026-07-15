"""Shared state and dependencies for all routers (aggregation layer).

This module is the backward-compatible aggregation/re-export point for
the ``api`` package. The implementation has been split into focused
submodules:

- ``api.constants``   — SSE headers and other cross-router constants
- ``api.stores``      — in-memory lists (news/article/publish), lookups
- ``api.schedule_state`` — scheduling knobs and crawl timestamps
- ``api.crawlers``    — NewsNow crawler registry + batch crawler instances
- ``api.singletons``  — interpreter, publishers, keyword filter, resolve_style
- ``api.content``     — article fetching/cleaning/ensure_content (~245 lines)

Routers keep importing as before — ``from . import deps; deps.X`` and
``from .deps import X`` both still work because everything is re-exported
here.

State names that are reassigned at runtime by ``app.py`` lifespan and
the schedule router (``news_store``, ``article_store``, ``publish_log``,
``schedule_running``, ``newsnow_interval``, ``rss_interval``,
``last_newsnow_crawl``, ``last_rss_crawl``) are NOT captured by a plain
``from .stores import news_store`` — that would freeze the value at
import time and silently break sharing once ``app.py`` reassigns the
source module. Instead they are resolved live via the module-level
``__getattr__`` (PEP 562) so ``deps.news_store`` always reflects the
current ``stores.news_store``. Mutations (``deps.news_store.append``)
go straight to the underlying object; **writes** to these names must
go to the source module (e.g. ``schedule_state.schedule_running = True``
in ``schedule.py``), not through ``deps`` — a ``deps.X = ...`` assign
shadows the delegation in ``deps.__dict__`` and never reaches the
source module, so the lifespan and the toggle endpoint would see
different values. Reads through ``deps`` always delegate correctly.
"""

# ruff: noqa: F822  __all__ lists runtime state names resolved via __getattr__ (PEP 562),
# which ruff's static analysis cannot see, so flag them as "undefined" — suppress file-wide.

from __future__ import annotations

# 保留 deps 原有从第三方库/重导出的符号，供引用方以 deps.X 形式访问（如
# deps.httpx、deps.HTTPException）。这些在拆分后 deps 本体不再直接使用，
# 仅作 re-export，故标注 noqa: F401。
import httpx  # noqa: F401
from fastapi import HTTPException  # noqa: F401

# 保留 deps 原有从 config/core/database/publishers/sources 的重导出，供引用方
# 以 deps.X 形式访问（如 deps.StyleType、deps.update_news_content、
# deps.DEFAULT_RSS_FEEDS、deps.PLATFORM_CONFIG）。拆分后 deps 本体不再直接
# 使用，仅作 re-export，故标注 noqa: F401。
from config import (  # noqa: F401
    JINA_READER_URL,
    KEYWORDS_FILE,
    KEYWORDS_FILTER_ENABLED,
    NEWSNOW_CRAWL_INTERVAL,
    RSS_CRAWL_INTERVAL,
)
from core import NewsInterpreter, StyleType  # noqa: F401
from database import update_news_content  # noqa: F401
from publishers import (  # noqa: F401
    DouyinPublisher,
    WechatMpPublisher,
    XiaohongshuPublisher,
)
from sources import (  # noqa: F401
    DEFAULT_RSS_FEEDS,
    PLATFORM_CONFIG,
    NewsNowBatchCrawler,
    NewsNowCrawler,
    RSSBatchCrawler,
)
from sources.filter import KeywordFilter  # noqa: F401

# ── Regular re-exports (stable objects, never reassigned by callers) ──
# 这些是函数/常量/单例/爬虫/锁；引用方通过 deps.X 访问，故在此重新导入。
from . import schedule_state as _schedule_state
from . import stores as _stores
from .constants import SSE_HEADERS
from .content import (
    JS_RENDERED_SOURCES,
    ensure_content,
    fetch_article_content,
    fetch_article_content_via_jina,
    is_limited_content,
)
from .crawlers import (
    NEWSNOW_CRAWLERS,
    newsnow_batch,
    rss_batch,
)
from .singletons import (
    PUBLISHERS,
    interpreter,
    kw_filter,
    resolve_style,
)
from .stores import (
    find_article,
    find_news,
    find_news_batch,
    invalidate_articles,
    invalidate_news,
    invalidate_publish_log,
)

# ── Lazy state delegation ────────────────────────────────────────────
# 这些名字在运行时会被 app.py lifespan / schedule 路由整体替换或改写，
# 故不能以 `from .stores import news_store` 的方式冻结绑定，改为在访问时
# 实时从源模块读取，保证 deps.X 与源模块始终指向同一个对象/值。
_STATE_DELEGATION = {
    "news_store": _stores,
    "article_store": _stores,
    "publish_log": _stores,
    "schedule_running": _schedule_state,
    "newsnow_interval": _schedule_state,
    "rss_interval": _schedule_state,
    "last_newsnow_crawl": _schedule_state,
    "last_rss_crawl": _schedule_state,
}


def __getattr__(name: str):
    """Resolve runtime-reassignable state names from their source modules.

    PEP 562 module-level ``__getattr__``: invoked only when ``name`` is
    absent from this module's ``__dict__``, so reads like
    ``deps.schedule_running`` always forward to the source module. A
    ``deps.schedule_running = X`` assign, however, would shadow the
    delegation in ``deps.__dict__`` and never reach the source module —
    which is why all writers (``app.py`` lifespan, ``schedule.py``) write
    the source module directly. See the module docstring for details.
    """
    module = _STATE_DELEGATION.get(name)
    if module is not None:
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ── __all__ for `from .deps import *` compatibility ──────────────────
# 枚举全部公共名字，含运行时由 __getattr__ 解析的状态名，使 `import *`
# 仍能取到这些名字（否则 `import *` 只看 __dict__，会漏掉状态名）。
__all__ = [
    # constants
    "SSE_HEADERS",
    # stores
    "news_store",
    "article_store",
    "publish_log",
    "find_news",
    "find_news_batch",
    "find_article",
    "invalidate_news",
    "invalidate_articles",
    "invalidate_publish_log",
    # schedule_state
    "schedule_running",
    "newsnow_interval",
    "rss_interval",
    "last_newsnow_crawl",
    "last_rss_crawl",
    # crawlers
    "NEWSNOW_CRAWLERS",
    "newsnow_batch",
    "rss_batch",
    # singletons
    "interpreter",
    "PUBLISHERS",
    "kw_filter",
    "resolve_style",
    # content
    "JS_RENDERED_SOURCES",
    "fetch_article_content",
    "fetch_article_content_via_jina",
    "ensure_content",
    "is_limited_content",
    # re-imports from config/core/database/sources/publishers
    "httpx",
    "HTTPException",
    "JINA_READER_URL",
    "KEYWORDS_FILE",
    "KEYWORDS_FILTER_ENABLED",
    "NEWSNOW_CRAWL_INTERVAL",
    "RSS_CRAWL_INTERVAL",
    "NewsInterpreter",
    "StyleType",
    "update_news_content",
    "DouyinPublisher",
    "WechatMpPublisher",
    "XiaohongshuPublisher",
    "DEFAULT_RSS_FEEDS",
    "PLATFORM_CONFIG",
    "NewsNowBatchCrawler",
    "NewsNowCrawler",
    "RSSBatchCrawler",
    "KeywordFilter",
]
