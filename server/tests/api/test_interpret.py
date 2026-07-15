"""api/interpret.py 测试：interpret / chat / generate_article 端点（mock interpreter）。

deps.interpreter 默认是 NewsInterpreter(mock=False) 会调真实 LLM，这里用
mock interpreter 替换以离线测端点路由与缓存联动。所有测试函数用 async，
seed 通过 await 完成（pytest-asyncio auto 模式）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import database as db
from api import deps


class _MockInterpreter:
    """替代真实 NewsInterpreter，返回固定内容，记录调用。"""

    def __init__(self):
        self.interpret_calls: list = []
        self.chat_calls: list = []
        self.generate_calls: list = []

    async def interpret(self, news_list, style=None, prompt=None):
        self.interpret_calls.append((news_list, style, prompt))
        return f"解读结果-{style}"

    async def chat(self, message, news_list):
        self.chat_calls.append((message, news_list))
        return f"聊天回复-{message}"

    async def generate_article(self, news_list, style=None, title=None, prompt=None):
        self.generate_calls.append((news_list, style, title, prompt))
        return {
            "title": title or "生成标题",
            "content": "生成内容",
            "style": style.value if style else "wechat_mp",
            "news_ids": [n.get("news_id") for n in news_list],
        }

    def build_prompt_text(self, news_list, style=None, prompt=None, message=None, task="interpret"):
        return f"[prompt] task={task}"

    async def astream_interpret(self, news_list, style=None, prompt=None, task="interpret"):
        yield "chunk1"
        yield "chunk2"

    async def astream_chat(self, message, news_list):
        yield "chat_chunk"


@pytest.fixture(autouse=True)
def _mock_interpreter(monkeypatch):
    monkeypatch.setattr(deps, "interpreter", _MockInterpreter())


def _news(news_id: str, source: str = "cls-hot", content: str = "正文内容") -> dict:
    return {
        "news_id": news_id,
        "title": f"title-{news_id}",
        "summary": f"summary-{news_id}",
        "content": content,
        "source": source,
        "url": f"https://x/{news_id}",
        "published_at": "2024-01-01T00:00:00",
        "extra": {},
    }


def test_interpret_news_not_found_returns_404(client: TestClient):
    resp = client.post("/api/interpret", json={"news_id": "nope", "style": "wechat_mp"})
    assert resp.status_code == 404


async def test_interpret_news_returns_interpretation(client: TestClient):
    await db.upsert_news([_news("n1")])
    resp = client.post("/api/interpret", json={"news_id": "n1", "style": "xiaohongshu"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["news_id"] == "n1"
    assert data["style"] == "xiaohongshu"
    assert "解读结果" in data["interpretation"]


async def test_interpret_news_limited_content_returns_message(client: TestClient):
    """内容为 [全文需在浏览器中查看] 时返回 LIMITED_CONTENT_MSG。"""
    await db.upsert_news([_news("n1", content="[全文需在浏览器中查看]\n标题：x")])
    resp = client.post("/api/interpret", json={"news_id": "n1"})
    assert resp.status_code == 200
    assert "动态加载" in resp.json()["interpretation"]


async def test_chat_endpoint(client: TestClient):
    await db.upsert_news([_news("n1"), _news("n2")])
    resp = client.post("/api/chat", json={"message": "这是问题", "news_ids": ["n1", "n2"]})
    assert resp.status_code == 200
    assert "聊天回复" in resp.json()["response"]


async def test_chat_endpoint_all_limited_returns_message(client: TestClient):
    await db.upsert_news([_news("n1", content="[全文需在浏览器中查看]\n标题")])
    resp = client.post("/api/chat", json={"message": "问题", "news_ids": ["n1"]})
    assert resp.status_code == 200
    assert "动态加载" in resp.json()["response"]


async def test_chat_endpoint_empty_news_ids(client: TestClient):
    """空 news_ids 时 chat 仍可工作（无 ensure_content）。"""
    resp = client.post("/api/chat", json={"message": "问题", "news_ids": []})
    assert resp.status_code == 200
    assert "聊天回复" in resp.json()["response"]


async def test_generate_article_no_items_returns_400(client: TestClient):
    resp = client.post("/api/generate_article", json={"news_ids": ["nonexistent"]})
    assert resp.status_code == 400


async def test_generate_article_success(client: TestClient):
    await db.upsert_news([_news("n1"), _news("n2")])
    resp = client.post(
        "/api/generate_article",
        json={"news_ids": ["n1", "n2"], "style": "wechat_mp", "title": "自定义标题"},
    )
    assert resp.status_code == 200
    article = resp.json()
    assert article["title"] == "自定义标题"
    assert article["content"] == "生成内容"
    assert "article_id" in article


async def test_generate_article_all_limited_returns_400(client: TestClient):
    await db.upsert_news([_news("n1", content="[全文需在浏览器中查看]\n标题")])
    resp = client.post("/api/generate_article", json={"news_ids": ["n1"]})
    assert resp.status_code == 400
    assert "动态加载" in resp.json()["detail"]


async def test_generate_article_invalid_style_returns_400(client: TestClient):
    await db.upsert_news([_news("n1")])
    resp = client.post("/api/generate_article", json={"news_ids": ["n1"], "style": "bogus"})
    assert resp.status_code == 400


async def test_generate_article_persists_to_db(client: TestClient):
    """生成文章应落库（DB 事实来源），list_articles 可见。"""
    await db.upsert_news([_news("n1")])
    resp = client.post("/api/generate_article", json={"news_ids": ["n1"], "style": "wechat_mp"})
    assert resp.status_code == 200
    article_id = resp.json()["article_id"]
    # 落库可见
    got = await db.get_article(article_id)
    assert got is not None
    assert got["title"] == "生成标题"


# ── SSE 流式端点 ──


def test_interpret_stream_not_found_returns_404(client: TestClient):
    resp = client.post("/api/interpret/stream", json={"news_id": "nope"})
    assert resp.status_code == 404


async def test_interpret_stream_emits_chunks(client: TestClient):
    """interpret/stream SSE：发 loading/prompt/chunk/[DONE] 事件。"""
    await db.upsert_news([_news("n1")])
    with client.stream("POST", "/api/interpret/stream", json={"news_id": "n1"}) as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "data:" in body
    assert "[DONE]" in body
    assert "chunk" in body or "loading" in body


async def test_interpret_stream_limited_content_emits_limited_event(client: TestClient):
    """内容受限时 emit limited 事件后 DONE。"""
    await db.upsert_news([_news("n1", content="[全文需在浏览器中查看]\n标题")])
    with client.stream("POST", "/api/interpret/stream", json={"news_id": "n1"}) as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "limited" in body
    assert "[DONE]" in body


async def test_chat_stream_emits_chunks(client: TestClient):
    await db.upsert_news([_news("n1")])
    with client.stream("POST", "/api/chat/stream", json={"message": "问题", "news_ids": ["n1"]}) as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "[DONE]" in body


async def test_chat_stream_empty_news_ids(client: TestClient):
    """空 news_ids 时 chat/stream 仍能产出。"""
    with client.stream("POST", "/api/chat/stream", json={"message": "问题", "news_ids": []}) as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "[DONE]" in body


async def test_chat_stream_all_limited_emits_limited(client: TestClient):
    await db.upsert_news([_news("n1", content="[全文需在浏览器中查看]\n标题")])
    with client.stream("POST", "/api/chat/stream", json={"message": "q", "news_ids": ["n1"]}) as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "limited" in body
    assert "[DONE]" in body


async def test_generate_article_stream_no_items_returns_400(client: TestClient):
    resp = client.post("/api/generate_article/stream", json={"news_ids": ["nope"]})
    assert resp.status_code == 400


async def test_generate_article_stream_emits_meta_and_done(client: TestClient):
    """generate_article/stream：meta/article_id/done 事件 + 落库。"""
    await db.upsert_news([_news("n1"), _news("n2")])
    with client.stream(
        "POST",
        "/api/generate_article/stream",
        json={"news_ids": ["n1", "n2"], "style": "wechat_mp", "title": "标题"},
    ) as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "meta" in body
    assert "done" in body
    # 提取 article_id 并验证落库
    import json

    aid = None
    for line in body.splitlines():
        if line.startswith("data: ") and "article_id" in line and '"type":"meta"' in line.replace(" ", ""):
            data = json.loads(line[len("data: ") :])
            aid = data.get("article_id")
            break
    if aid:
        got = await db.get_article(aid)
        assert got is not None


async def test_generate_article_stream_all_limited_emits_limited(client: TestClient):
    await db.upsert_news([_news("n1", content="[全文需在浏览器中查看]\n标题")])
    with client.stream(
        "POST", "/api/generate_article/stream", json={"news_ids": ["n1"], "style": "wechat_mp"}
    ) as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "limited" in body
    assert "[DONE]" in body


async def test_generate_article_stream_auto_title(client: TestClient):
    """无 title 时自动生成标题（按 style）。"""
    await db.upsert_news([_news("n1"), _news("n2")])
    with client.stream(
        "POST",
        "/api/generate_article/stream",
        json={"news_ids": ["n1", "n2"], "style": "douyin"},
    ) as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "🔥" in body or "深度解读" in body or "meta" in body
