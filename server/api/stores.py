"""In-memory stores, concurrency locks, and lookup helpers.

Owns the shared mutable lists (``news_store`` / ``article_store`` /
``publish_log``) plus the asyncio locks guarding them, and the small
``find_news`` / ``find_news_batch`` / ``find_article`` lookup helpers that
read those lists.

These lists are reassigned at runtime by ``app.py`` lifespan (loading
persisted data from the DB), so ``api.deps`` resolves them live via its
module-level ``__getattr__`` rather than a frozen re-import — see
``deps.py`` for the delegation table.
"""

from __future__ import annotations

import asyncio
from typing import Any

# ── In-memory stores ──────────────────────────────────────────────────
# 由 app.py lifespan 在启动时整体替换为从 DB 加载的持久化数据；
# 运行时由各路由追加/清空。使用 list 顺序容器，避免并发哈希冲突。
news_store: list[dict[str, Any]] = []
article_store: list[dict[str, Any]] = []
publish_log: list[dict[str, Any]] = []

# ── Concurrency locks ─────────────────────────────────────────────────
# 保护 news_store / article_store 的并发写入（爬虫循环、刷新端点、agent 工具）。
news_lock = asyncio.Lock()
article_lock = asyncio.Lock()

# ── Lookup helpers ────────────────────────────────────────────────────


def find_news(news_id: str) -> dict | None:
    """按 news_id 在 news_store 中查找单条新闻。"""
    return next((n for n in news_store if n["news_id"] == news_id), None)


def find_news_batch(ids: list[str]) -> list[dict]:
    """按 news_id 批量查找，返回 news_store 中命中的全部新闻（顺序保留）。"""
    return [n for n in news_store if n["news_id"] in ids]


def find_article(article_id: str) -> dict | None:
    """按 article_id 在 article_store 中查找单条已生成文章。"""
    return next((a for a in article_store if a.get("article_id") == article_id), None)
