"""In-memory caches (DB is the source of truth), locks, and lookup helpers.

``news_store`` / ``article_store`` / ``publish_log`` are now treated as
**caches** over the SQLite tables. The database is the single source of
truth: every write first hits the DB then invalidates/updates the cache;
every read tries the cache and falls back to the DB on a miss (backfilling
the cache with the returned object).

``find_news`` / ``find_news_batch`` / ``find_article`` return the *cached*
dict objects when present, so existing in-place mutations of the returned
item (e.g. ``item["content"] = ...`` in ``content.ensure_content``) keep the
cache fresh — this preserves the original shared-reference semantics the
readers rely on. On a cache miss they query the DB and append the result to
the cache list, returning that shared object.

``app.py`` lifespan still reassigns these lists (loaded from the DB) for a
fast warm start; ``api.deps`` resolves them live via its module-level
``__getattr__`` (see ``deps.py``). When a reassignment happens the old cache
is simply replaced — invalidations target the currently-bound list.
"""

from __future__ import annotations

import asyncio
from typing import Any

import database

# ── In-memory caches (DB is source of truth) ──────────────────────────
# news_store / article_store / publish_log 是缓存的列表容器。
# - 启动时由 app.py lifespan 用 DB 全量结果整体替换（预热）。
# - 运行时写先落 DB 再 invalidate/update 缓存；读优先缓存命中，未命中回源 DB 回填。
# - 保留 list 而非 dict，是为了让 find_* 返回的共享对象支持原地字段更新
#   （content.py 的 ensure_content 依赖 item["content"] = ... 原地写入同时
#   通过 update_news_content 落库，缓存条目随之保持新鲜）。
news_store: list[dict[str, Any]] = []
article_store: list[dict[str, Any]] = []
publish_log: list[dict[str, Any]] = []

# ── Concurrency locks ─────────────────────────────────────────────────
# 保护 news_store / article_store 的并发写入临界区（"DB 查重 + DB 写 + 缓存失效"）。
# publish_log 的写改走纯 DB（save_publish_record 是单条 INSERT，WAL 下并发安全），
# 不再依赖 article_lock。
news_lock = asyncio.Lock()
article_lock = asyncio.Lock()


# ── Cache invalidation ─────────────────────────────────────────────────


def invalidate_news(news_id: str | None = None, source: str | None = None) -> None:
    """失效 news 缓存。

    - 不带参数：清空整个 news_store（refresh_news 的"重新刷新全部"语义）。
    - news_id：移除/标记指定条目（下一读取会回源 DB 回填）。
    - source：失效该 source 下全部条目（content 清缓存用）。

    实现上对单条/按 source 失效直接从缓存移除对应条目；下一次 find_news /
    列表读取会回源 DB 回填。整体失效直接清空列表。
    """
    if news_id is None and source is None:
        news_store.clear()
        return
    if news_id is not None:
        for i, n in enumerate(news_store):
            if n.get("news_id") == news_id:
                news_store.pop(i)
                return
        return
    # source is not None
    news_store[:] = [n for n in news_store if n.get("source") != source]


def invalidate_articles() -> None:
    """失效 article 缓存（整表）。文章数据量小，统一整体失效，下次列表读回源 DB。"""
    article_store.clear()


def invalidate_publish_log() -> None:
    """失效 publish_log 缓存（整表）。写 publish_log 后调用。"""
    publish_log.clear()


# ── Lookup helpers ────────────────────────────────────────────────────


async def find_news(news_id: str) -> dict | None:
    """按 news_id 查找单条新闻。

    优先在 news_store 缓存中查找（命中即返回缓存里的共享对象，保留原地更新语义）；
    未命中回源 DB（get_news），命中则回填缓存并返回该共享对象，DB 无则返回 None。
    """
    cached = next((n for n in news_store if n["news_id"] == news_id), None)
    if cached is not None:
        return cached
    item = await database.get_news(news_id)
    if item is not None:
        news_store.append(item)
    return item


async def find_news_batch(ids: list[str]) -> list[dict]:
    """按 news_id 批量查找，返回命中的全部新闻（顺序按 DB published_at DESC）。

    缓存命中的直接返回缓存对象；未命中的回源 DB（get_news_batch）并回填缓存。
    返回顺序：先缓存命中项（保持缓存里的相对顺序），再 DB 命中项（DB 排序）。
    """
    if not ids:
        return []
    ids_set = set(ids)
    cached = [n for n in news_store if n["news_id"] in ids_set]
    cached_ids = {n["news_id"] for n in cached}
    missing_ids = [i for i in ids if i not in cached_ids]
    if not missing_ids:
        return cached
    fetched = await database.get_news_batch(missing_ids)
    news_store.extend(fetched)
    return cached + fetched


async def find_article(article_id: str) -> dict | None:
    """按 article_id 查找单条已生成文章。

    优先在 article_store 缓存中查找；未命中回源 DB（get_article），命中则
    回填缓存并返回该对象，DB 无则返回 None。
    """
    cached = next((a for a in article_store if a.get("article_id") == article_id), None)
    if cached is not None:
        return cached
    article = await database.get_article(article_id)
    if article is not None:
        article_store.append(article)
    return article
