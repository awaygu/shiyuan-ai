import os
from unittest.mock import AsyncMock

os.environ.setdefault("LLM_API_KEY", "dummy")
os.environ.setdefault("DASHSCOPE_API_KEY", "dummy")
os.environ.setdefault("TAVILY_API_KEY", "dummy")
os.environ.setdefault("MOONSHOT_API_KEY", "dummy")

import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import app

# 缩短测试启动时间：跳过 NewsNow 健康检查和启动时全量爬取
app_module._wait_for_newsnow = AsyncMock()
app_module.newsnow_batch.crawl_all = AsyncMock(return_value={})
app_module.rss_batch.crawl_all = AsyncMock(return_value={})


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
