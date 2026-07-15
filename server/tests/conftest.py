"""Shared pytest fixtures for the FastAPI backend.

All external I/O (NewsNow health checks, crawlers, LLM) is mocked so tests
run offline and quickly.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# ── Set environment variables BEFORE importing app/config/database ─────────────
# config.py reads these at import time; database.py also evaluates DB_PATH eagerly.
_TEST_DIR = Path(tempfile.mkdtemp(prefix="shiyuan_test_"))

os.environ.setdefault("NEWS_AI_DB_PATH", str(_TEST_DIR / "news_ai.db"))
os.environ.setdefault("MEMORY_DB_PATH", str(_TEST_DIR / "agent_memory.db"))
os.environ.setdefault("KB_RAG_MEMORY_DB_PATH", str(_TEST_DIR / "rag_memory.db"))
os.environ.setdefault("MOONSHOT_API_KEY", "dummy")
os.environ["SCHEDULE_ENABLED"] = "false"
os.environ["LLM_API_KEY"] = "dummy"
os.environ["DASHSCOPE_API_KEY"] = "dummy"
os.environ["TAVILY_API_KEY"] = "dummy"

# ruff: noqa: E402
from fastapi.testclient import TestClient

import api.crawlers as crawlers
import app as app_module
import database as db


async def _true(*args, **kwargs) -> bool:
    return True


async def _empty_dict(*args, **kwargs) -> dict:
    return {}


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_dir() -> None:
    """Remove the temporary test directory after the whole test session."""
    yield
    shutil.rmtree(_TEST_DIR, ignore_errors=True)


@pytest.fixture()
async def client(monkeypatch, tmp_path) -> TestClient:
    """Yield a TestClient with mocked external dependencies.

    Each test gets its own isolated SQLite database under ``tmp_path``.
    In-memory caches (news_store / article_store / publish_log) are cleared
    before and after each test, and any stale ``deps`` shadow attributes left
    by other tests' ``monkeypatch.setattr(deps, "news_store", ...)`` are removed
    so ``deps`` re-delegates to ``stores`` cleanly.
    """
    # Use a fresh database file for each test.
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai.db")
    await db.close_db()
    monkeypatch.setattr(db, "_db", None)

    # checkpointer 用同步 sqlite3，DB_PATH 在 init_db 时设为模块全局。
    # 启动时 lifespan 用 session 级 MEMORY_DB_PATH 调 init_memory_db 重新设置 DB_PATH，
    # 故每测试独立 DB_PATH 必须在 TestClient 启动（lifespan 跑完）之后重置，否则会被
    # 覆盖回 session 级共享路径，导致跨测试数据污染。与主 DB 同样的隔离语义（仿上面对
    # db.DB_PATH 的处理）。init_db 重新建表，确保新库 schema 就绪。

    # Avoid any real network calls during lifespan / startup.
    # newsnow_batch / rss_batch 现归 crawlers 模块所有（deps 通过 __getattr__/
    # re-export 转发到同一对象），直接 patch 源模块上的对象方法。
    monkeypatch.setattr(app_module, "check_newsnow_health", _true)
    monkeypatch.setattr(crawlers.newsnow_batch, "crawl_all", _empty_dict)
    monkeypatch.setattr(crawlers.rss_batch, "crawl_all", _empty_dict)

    # Clear in-memory caches + drop stale deps shadows so every client test
    # starts from a clean slate (cross-test cache pollution otherwise leaks
    # via the process-wide stores lists).
    from api import deps as _deps
    from api import stores as _stores

    for _name in ("news_store", "article_store", "publish_log"):
        if _name in _deps.__dict__:
            del _deps.__dict__[_name]
    _stores.news_store.clear()
    _stores.article_store.clear()
    _stores.publish_log.clear()

    with TestClient(app_module.app) as test_client:
        # lifespan 已跑完，此时 checkpointer.DB_PATH 被 init_memory_db 设回 session 级
        # 共享路径。重置为每测试独立 tmp_path 并重新建表，隔离 checkpointer 数据。
        import core.checkpointer as _checkpointer
        _checkpointer.DB_PATH = str(tmp_path / "agent_memory.db")
        _checkpointer.init_db(_checkpointer.DB_PATH)
        yield test_client

    await db.close_db()
    # Tear down: clear caches + remove shadows again.
    for _name in ("news_store", "article_store", "publish_log"):
        if _name in _deps.__dict__:
            del _deps.__dict__[_name]
    _stores.news_store.clear()
    _stores.article_store.clear()
    _stores.publish_log.clear()
