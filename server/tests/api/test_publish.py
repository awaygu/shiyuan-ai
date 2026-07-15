"""api/publish.py 测试：发布/登录/状态/列表端点（mock publisher，离线）。

publish 流程涉及 Playwright，用 fake publisher 替换 deps.PUBLISHERS，
验证端点路由、参数校验、publish_log 落库（DB 事实来源）、列表分页。
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

import database as db
from api import deps
from publishers.base import PublishResult


class _FakePublisher:
    """替代真实 Playwright publisher，记录调用并可控返回结果。"""

    def __init__(self, name: str = "fake", *, login_ok=True, check_ok=True, publish_ok=True, need_login=False):
        self.name = name
        self._login_ok = login_ok
        self._check_ok = check_ok
        self._publish_ok = publish_ok
        self._need_login = need_login
        self.publish_calls: list = []
        self._last_login_error = ""

    async def do_login(self):
        return self._login_ok

    async def check_login(self):
        return self._check_ok

    async def publish(self, title, content, generate_cover=True, generate_inline_images=False, on_progress=None):
        self.publish_calls.append((title, content))
        if on_progress:
            await on_progress("步骤1")
        if self._publish_ok:
            return PublishResult(
                success=True,
                platform=self.name,
                article_title=title,
                published_url="https://published.example.com/x",
                published_at=datetime.now(),
            )
        return PublishResult(
            success=False,
            platform=self.name,
            article_title=title,
            error_message="发布失败模拟",
            need_login=self._need_login,
        )


def _patch_publishers(monkeypatch, **kwargs):
    fakes = {
        "xiaohongshu": _FakePublisher("xiaohongshu", **kwargs),
        "wechat_mp": _FakePublisher("wechat_mp", **kwargs),
        "douyin": _FakePublisher("douyin", **kwargs),
    }
    monkeypatch.setattr(deps, "PUBLISHERS", fakes)
    return fakes


def test_publish_unknown_platform_returns_400(client: TestClient, monkeypatch):
    _patch_publishers(monkeypatch)
    resp = client.post("/api/publish", json={"platform": "nope", "title": "t", "content": "c"})
    assert resp.status_code == 400


def test_publish_missing_title_and_content_returns_400(client: TestClient, monkeypatch):
    _patch_publishers(monkeypatch)
    resp = client.post("/api/publish", json={"platform": "xiaohongshu"})
    assert resp.status_code == 400


def test_publish_with_article_id_not_found_returns_404(client: TestClient, monkeypatch):
    _patch_publishers(monkeypatch)
    resp = client.post("/api/publish", json={"platform": "xiaohongshu", "article_id": "nope"})
    assert resp.status_code == 404


def test_publish_creates_task_and_returns_pending(client: TestClient, monkeypatch):
    _patch_publishers(monkeypatch)
    resp = client.post(
        "/api/publish",
        json={"platform": "xiaohongshu", "title": "测试标题", "content": "测试内容"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "pending"


def test_publish_with_full_title_content_skips_article_lookup(client: TestClient, monkeypatch):
    """article_id + title + content 齐全时不查文章，直接发布。"""
    _patch_publishers(monkeypatch)
    resp = client.post(
        "/api/publish",
        json={"platform": "xiaohongshu", "article_id": "art_x", "title": "标题", "content": "正文"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_login_unknown_platform_returns_400(client: TestClient, monkeypatch):
    _patch_publishers(monkeypatch)
    resp = client.post("/api/publish/nope/login")
    assert resp.status_code == 400


def test_login_success(client: TestClient, monkeypatch):
    _patch_publishers(monkeypatch, login_ok=True)
    resp = client.post("/api/publish/xiaohongshu/login")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["platform"] == "xiaohongshu"


def test_login_failure_returns_error_message(client: TestClient, monkeypatch):
    _patch_publishers(monkeypatch, login_ok=False)
    resp = client.post("/api/publish/xiaohongshu/login")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_message"]


def test_status_unknown_platform_returns_400(client: TestClient, monkeypatch):
    _patch_publishers(monkeypatch)
    resp = client.get("/api/publish/nope/status")
    assert resp.status_code == 400


def test_status_logged_in(client: TestClient, monkeypatch):
    _patch_publishers(monkeypatch, check_ok=True)
    resp = client.get("/api/publish/xiaohongshu/status")
    assert resp.status_code == 200
    assert resp.json()["logged_in"] is True


def test_status_not_logged_in(client: TestClient, monkeypatch):
    """check_login 抛异常时 logged_in=False 且 error_message 被填充。"""
    fakes = _patch_publishers(monkeypatch)

    class _CheckError(Exception):
        pass

    async def _raise():
        raise _CheckError("cookies 过期")

    monkeypatch.setattr(fakes["xiaohongshu"], "check_login", _raise)
    resp = client.get("/api/publish/xiaohongshu/status")
    assert resp.status_code == 200
    assert resp.json()["logged_in"] is False
    assert resp.json()["error_message"]


def test_publish_log_endpoint_empty(client: TestClient):
    resp = client.get("/api/publish_log")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_articles_endpoint_empty(client: TestClient):
    resp = client.get("/api/articles")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


async def test_publish_log_pagination(client: TestClient):
    """落库 3 条 publish_log，分页返回正确 total/limit（DB 事实来源）。"""
    for i in range(3):
        await db.save_publish_record(
            {
                "article_id": f"art_{i}",
                "platform": "xiaohongshu",
                "success": True,
                "url": "",
                "timestamp": f"2024-01-0{i+1}T00:00:00",
                "extra": {},
            }
        )
    resp = client.get("/api/publish_log?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2


async def test_articles_pagination(client: TestClient):
    for i in range(3):
        await db.save_article(
            {"article_id": f"art_{i}", "title": f"t{i}", "content": "c", "style": "s", "news_ids": []}
        )
    resp = client.get("/api/articles?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2


async def test_publish_log_orders_desc_by_id(client: TestClient):
    """publish_log 按 id DESC，最后插入排最前。"""
    for i in range(3):
        await db.save_publish_record(
            {
                "article_id": f"art_{i}",
                "platform": "p",
                "success": True,
                "url": "",
                "timestamp": "2024-01-01T00:00:00",
                "extra": {},
            }
        )
    resp = client.get("/api/publish_log?limit=10")
    data = resp.json()
    assert data["items"][0]["article_id"] == "art_2"
    assert data["items"][-1]["article_id"] == "art_0"
