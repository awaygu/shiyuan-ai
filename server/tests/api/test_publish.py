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


# ── 阶段3任务12：统一错误信封 + 429 守卫 + _safe_run 异常吞并 ──────────────
#
# 验证 publish 路由的错误返回对齐到 errors.py 统一信封
# （{"detail", "code", "type"}），429 并发守卫信封化，以及
# _safe_run_publish_task 吞掉初始化异常并标记 task failed。


def _assert_error_envelope(body, *, code, type_="http_error"):
    """断言返回体为统一错误信封三字段结构（复用 test_errors.py 的断言风格）。"""
    assert "detail" in body
    assert body["code"] == code
    assert body["type"] == type_


def test_publish_unknown_platform_envelope_lists_available(client: TestClient, monkeypatch):
    """未知平台 400 返回统一信封，detail 含可用平台列表（透传 available=...）。"""
    _patch_publishers(monkeypatch)
    resp = client.post("/api/publish", json={"platform": "nope", "title": "t", "content": "c"})
    assert resp.status_code == 400
    body = resp.json()
    _assert_error_envelope(body, code=400)
    # unknown_platform(available=...) 透传可用平台列表到 detail
    assert "Unknown platform: nope" in body["detail"]
    assert "xiaohongshu" in body["detail"]
    assert "wechat_mp" in body["detail"]


def test_login_unknown_platform_envelope(client: TestClient, monkeypatch):
    """登录端未知平台 400 统一信封。"""
    _patch_publishers(monkeypatch)
    resp = client.post("/api/publish/nope/login")
    assert resp.status_code == 400
    _assert_error_envelope(resp.json(), code=400)


def test_status_unknown_platform_envelope(client: TestClient, monkeypatch):
    """状态端未知平台 400 统一信封。"""
    _patch_publishers(monkeypatch)
    resp = client.get("/api/publish/nope/status")
    assert resp.status_code == 400
    _assert_error_envelope(resp.json(), code=400)


def test_publish_article_not_found_envelope(client: TestClient, monkeypatch):
    """article_id 不存在 → 404 统一信封，detail 含 article_id。"""
    _patch_publishers(monkeypatch)
    resp = client.post("/api/publish", json={"platform": "xiaohongshu", "article_id": "nope"})
    assert resp.status_code == 404
    body = resp.json()
    _assert_error_envelope(body, code=404)
    assert "Article not found: nope" in body["detail"]


def test_publish_missing_title_and_content_envelope(client: TestClient, monkeypatch):
    """缺 title/content → 400 统一信封（补强原 status_code 断言）。"""
    _patch_publishers(monkeypatch)
    resp = client.post("/api/publish", json={"platform": "xiaohongshu"})
    assert resp.status_code == 400
    body = resp.json()
    _assert_error_envelope(body, code=400)
    assert "title and content are required" in body["detail"]


async def test_login_429_when_lock_held(client: TestClient, monkeypatch):
    """lock 已被占用时登录 → 429 统一信封 + Retry-After header。

    占住模块级 _publish_locks[xiaohongshu]，发请求应乐观早退返回 429；
    全局 exception_handler 自动加 code/type，headers 透传 Retry-After。
    """
    import api.publish as publish_mod

    _patch_publishers(monkeypatch)
    lock = publish_mod._get_lock("xiaohongshu")
    # 占住 lock（模拟另一任务正在执行登录），用 try/finally 确保释放
    await lock.acquire()
    try:
        resp = client.post("/api/publish/xiaohongshu/login")
        assert resp.status_code == 429
        body = resp.json()
        _assert_error_envelope(body, code=429)
        assert "xiaohongshu" in body["detail"]
        # Retry-After header 透传（健壮性提升，提示客户端稍后重试）
        assert resp.headers.get("Retry-After") == "5"
    finally:
        lock.release()


async def test_safe_run_publish_task_swallows_init_exception_and_marks_failed(monkeypatch):
    """_safe_run_publish_task 吞掉 _run_publish_task 抛出的初始化异常并标记 task failed。

    直接单测 _safe_run_publish_task：mock _run_publish_task 抛 RuntimeError("boom")，
    验证它捕获异常并调 task_manager.update_task(status="failed", error="boom")，
    而非让异常向上传播（否则 create_task 会静默吞）。
    """
    import api.publish as publish_mod
    from api.tasks import AsyncTask, TaskManager

    # 用一个独立 TaskManager 实例避免污染单例 tasks 字典
    mgr = TaskManager()
    mgr.tasks.clear()
    mgr._subscribers.clear()
    task = AsyncTask(task_id="tboom", task_type="publish", platform="xiaohongshu", title="t")
    mgr.tasks[task.task_id] = task

    # mock task_manager 单例的 update_task 到本实例（_safe_run_publish_task 内部
    # `from .tasks import task_manager` 拿到的是单例，故 patch 单例方法）。
    from api.tasks import task_manager as singleton_mgr

    captured: list = []

    async def _fake_update(task_id, status=None, progress=None, result=None, error=None, need_login=None):
        captured.append((task_id, status, progress, error))
        # 同步到独立实例以便断言
        if task_id in mgr.tasks and status is not None:
            mgr.tasks[task_id].status = status
        if task_id in mgr.tasks and error is not None:
            mgr.tasks[task_id].error = error

    monkeypatch.setattr(singleton_mgr, "update_task", _fake_update)

    # mock _run_publish_task 抛异常（模拟初始化阶段失败，如 update_task("running") 抛错）
    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(publish_mod, "_run_publish_task", _boom)

    # _safe_run_publish_task 应吞掉异常，不应抛出
    await publish_mod._safe_run_publish_task(task=task, publisher=None, title="t", content="c")

    # 验证 update_task 被以 failed + "boom" 调用
    assert any(c[0] == "tboom" and c[1] == "failed" and "boom" in (c[3] or "") for c in captured)
    assert mgr.tasks["tboom"].status == "failed"
    assert "boom" in (mgr.tasks["tboom"].error or "")

