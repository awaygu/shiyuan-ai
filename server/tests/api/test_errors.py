"""阶段3任务10 测试：全局 exception_handler + sse_error helper + briefing SSE error。

覆盖：
1. 全局 handler 三类（HTTPException / RequestValidationError / 未捕获 Exception）
   的统一响应格式（envelope 保留 detail 兼容 + code/type 扩展）。
2. sse_error helper 输出格式（含/不含 code）。
3. briefing_stream 异常时发 SSE error 事件。
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import database as db
from api.errors import bad_request, not_found, server_error, unknown_platform
from api.sse import sse_error

# ── errors helper（HTTPException helper）──


def test_not_found_helper_raises_404():
    with pytest.raises(HTTPException) as exc:
        not_found("Knowledge base not found")
    assert exc.value.status_code == 404
    assert exc.value.detail == "Knowledge base not found"


def test_bad_request_helper_raises_400():
    with pytest.raises(HTTPException) as exc:
        bad_request("内容为空")
    assert exc.value.status_code == 400
    assert exc.value.detail == "内容为空"


def test_server_error_helper_raises_500_with_prefix():
    with pytest.raises(HTTPException) as exc:
        server_error("Embedding failed", ValueError("boom"))
    assert exc.value.status_code == 500
    assert exc.value.detail == "Embedding failed: boom"


def test_unknown_platform_helper_lists_available():
    with pytest.raises(HTTPException) as exc:
        unknown_platform("nope", available=["wechat_mp", "douyin"])
    assert exc.value.status_code == 400
    assert "Unknown platform: nope" in exc.value.detail
    assert "wechat_mp" in exc.value.detail


# ── sse_error helper ──


def test_sse_error_basic():
    line = sse_error("处理失败")
    assert line.endswith("\n\n")
    assert line.startswith("data: ")
    payload = json.loads(line[len("data: "):].strip())
    assert payload["type"] == "error"
    assert payload["message"] == "处理失败"
    # 不传 code 时不带 code 字段（前端不读，仅扩展用）
    assert "code" not in payload


def test_sse_error_with_code():
    line = sse_error("Embedding failed", code=500)
    payload = json.loads(line[len("data: "):].strip())
    assert payload["type"] == "error"
    assert payload["message"] == "Embedding failed"
    assert payload["code"] == 500


def test_sse_error_chinese_not_escaped():
    """ensure_ascii=False 保证中文原文输出，前端可直接渲染。"""
    line = sse_error("知识库为空")
    assert "知识库为空" in line
    assert "\\u" not in line


# ── 全局 exception_handler：HTTPException 标准化 ──


def test_http_exception_envelope_preserves_detail(client: TestClient):
    """HTTPException 响应保留 detail 兼容字段 + code/type 扩展。

    用 GET /api/news/{news_id}/content（不存在的 id 抛 404 HTTPException）验证。
    """
    resp = client.get("/api/news/nonexistent-id/content")
    assert resp.status_code == 404
    body = resp.json()
    # detail 兼容字段保留（FastAPI 默认 HTTPException 返回 {"detail": msg}）
    assert "detail" in body
    assert "nonexistent-id" in body["detail"]
    # 扩展字段
    assert body["code"] == 404
    assert body["type"] == "http_error"


async def test_http_exception_400_envelope(client: TestClient):
    """400 HTTPException 同样标准化为统一 envelope。

    用 interpret 路由的 generate_article（invalid style 抛 400）验证。
    """
    await db.upsert_news(
        [{"news_id": "n1", "title": "标题", "summary": "摘要", "content": "正文", "source": "cls-hot", "url": "u", "published_at": "2024-01-01", "extra": {}}]
    )
    resp = client.post("/api/generate_article", json={"news_ids": ["n1"], "style": "bogus"})
    assert resp.status_code == 400
    body = resp.json()
    assert "detail" in body
    assert body["code"] == 400
    assert body["type"] == "http_error"


# ── 全局 exception_handler：RequestValidationError 422 ──


def test_validation_error_envelope(client: TestClient):
    """RequestValidationError 422 统一格式：detail 保留 errors 列表 + code/type 扩展。

    用 GET /api/news?limit=0 触发 limit 的 ge=1 校验失败。
    """
    resp = client.get("/api/news?limit=0")
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 422
    assert body["type"] == "validation_error"
    # detail 保留 FastAPI 原始的 errors 列表结构
    assert isinstance(body["detail"], list)
    assert len(body["detail"]) >= 1


# ── 全局 exception_handler：未捕获 Exception 兜底 500 ──


def test_unhandled_exception_envelope(client: TestClient, monkeypatch):
    """未捕获 Exception 兜底 500：记 trace 返回结构化 detail，不泄露内部异常文本。

    用 GET /api/news（list_news）mock 抛 RuntimeError 触发兜底 handler。注意：

    - news.py 以 ``from database import list_news`` 绑定，需 patch
      ``api.news.list_news``（news 模块命名空间内的引用）才生效。
    - Starlette 0.27 的 ServerErrorMiddleware 在调用 handler 后仍会 re-raise，
      TestClient 默认 ``raise_server_exceptions=True`` 会把异常抛回测试。故
      用 ``raise_server_exceptions=False`` 的内部 TestClient（复用同一 app，
      不重跑 lifespan）读取 handler 返回的 500 响应体。生产行为（uvicorn）
      不 re-raise，handler 正常返回 500 envelope。
    """
    import api.news as news_mod

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom-internal-detail")

    monkeypatch.setattr(news_mod, "list_news", _boom)
    inner = TestClient(client.app, raise_server_exceptions=False)
    resp = inner.get("/api/news")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == 500
    assert body["type"] == "server_error"
    # 兜底 detail 为通用文案，不泄露内部异常文本（避免暴露堆栈细节给客户端）
    assert body["detail"] == "Internal server error"
    assert "boom-internal-detail" not in json.dumps(body)


# ── briefing_stream SSE error 补全 ──


def test_briefing_stream_emits_sse_error_on_llm_failure(client: TestClient, monkeypatch):
    """briefing_stream LLM 异常时应发 SSE error 事件而非裸连接中断。

    mock NewsInterpreter 的 llm.astream 抛异常，验证流中出现 type=error 事件。
    """

    class _BoomLLM:
        async def astream(self, messages):
            raise RuntimeError("LLM 不可用")
            yield  # 让 astream 成为 async generator（raise 后不可达，但 Python 据此识别生成器）

    class _FakeInterpreter:
        def __init__(self, mock=False):
            self.llm = _BoomLLM()

    import api.agent as agent_mod

    monkeypatch.setattr(agent_mod, "NewsInterpreter", _FakeInterpreter)

    # 预置新闻数据，使 briefing_stream 走 SSE 流式分支（非空 store 才不返回 JSON）
    from api import stores

    stores.news_store.clear()
    stores.news_store.extend(
        [{"news_id": "n1", "title": "测试新闻", "summary": "摘要", "source": "cls-hot", "url": "u"}]
    )

    resp = client.post("/api/agent/briefing/stream")
    assert resp.status_code == 200
    text = resp.text
    # meta / loading 事件应已发出
    assert '"type": "meta"' in text or '"type":"meta"' in text
    # 关键：异常时应发 error 事件（前端 onError 读 message）
    assert '"type": "error"' in text or '"type":"error"' in text
    assert "生成简报失败" in text
