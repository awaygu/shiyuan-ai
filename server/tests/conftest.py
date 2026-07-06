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

import api.deps as deps
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
    """
    # Use a fresh database file for each test.
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai.db")
    await db.close_db()
    monkeypatch.setattr(db, "_db", None)

    # Avoid any real network calls during lifespan / startup.
    monkeypatch.setattr(app_module, "check_newsnow_health", _true)
    monkeypatch.setattr(deps.newsnow_batch, "crawl_all", _empty_dict)
    monkeypatch.setattr(deps.rss_batch, "crawl_all", _empty_dict)

    with TestClient(app_module.app) as test_client:
        yield test_client

    await db.close_db()
