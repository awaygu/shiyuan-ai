"""api/agent.py 测试：trends / search / compare / execute 端点 + _extract_keywords。

不依赖 LLM 的端点直接测；compare 走真实 LLM 的路径通过 mock interpreter 跳过。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api import deps, stores
from api.agent import _extract_keywords


def _populate_news_store(monkeypatch, items: list[dict]):
    """填充 news_store 缓存（agent 的 trends/search/briefing 读缓存）。

    直接写 stores.news_store（deps.news_store 经 __getattr__ 委托到同一对象），
    不用 monkeypatch.setattr(deps, "news_store", ...) 建 shadow —— 因为 deps
    用 PEP 562 __getattr__，shadow 在 teardown 时会被 monkeypatch 恢复为
    "捕获时的列表对象"而非删除，导致后续测试 deps.news_store 不再委托、
    与 invalidate_news 清的真实 stores.news_store 脱节。conftest 的 client
    fixture 已在每个测试前后清空 stores 并移除残留 shadow。
    """
    stores.news_store.clear()
    stores.news_store.extend(items)


# ── _extract_keywords ──


def test_extract_keywords_chinese():
    text = "人工智能芯片市场迎来重大突破。人工智能需求持续增长。半导体产业快速发展。"
    kws = _extract_keywords(text, top_n=5)
    assert len(kws) > 0
    # 正则 [一-鿿]{2,6} 贪婪切词，"人工智能"作为更长词的子串可能不单独出现，
    # 这里验证返回的是 (词, 频次) 元组且含中文关键词。
    found = dict(kws)
    # 至少命中一个含"人工智能"的词
    assert any("人工智能" in w for w in found)


def test_extract_keywords_filters_stopwords_and_urls():
    text = "https://example.com/article 这是一个测试，的 了 在 是 公司市场。"
    kws = _extract_keywords(text, top_n=10)
    words = [w for w, _ in kws]
    # 停用词不应出现
    assert "的" not in words
    assert "了" not in words
    assert "在" not in words
    assert "公司" not in words  # 公司在停用词表


def test_extract_keywords_empty_text():
    assert _extract_keywords("", top_n=5) == []


# ── /api/agent/trends ──


def test_trends_empty_store(client: TestClient, monkeypatch):
    monkeypatch.setattr(deps, "news_store", [])
    resp = client.get("/api/agent/trends")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trends"] == []
    assert data["total_news"] == 0


def test_trends_with_news(client: TestClient, monkeypatch):
    _populate_news_store(
        monkeypatch,
        [
            {
                "news_id": "n1",
                "title": "人工智能芯片突破",
                "summary": "半导体产业增长",
                "source": "cls-hot",
                "url": "u1",
            },
            {"news_id": "n2", "title": "人工智能应用落地", "summary": "ai 技术发展", "source": "rss-x", "url": "u2"},
        ],
    )
    resp = client.get("/api/agent/trends?top_n=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_news"] == 2
    assert len(data["trends"]) <= 5
    # 每条 trend 有 keyword/count/source_count/related_news
    if data["trends"]:
        t = data["trends"][0]
        assert "keyword" in t
        assert "count" in t
        assert "source_count" in t
        assert "related_news" in t


# ── /api/agent/search ──


def test_search_no_match(client: TestClient, monkeypatch):
    _populate_news_store(
        monkeypatch,
        [{"news_id": "n1", "title": "标题", "summary": "摘要", "content": "", "source": "s", "url": "u"}],
    )
    resp = client.get("/api/agent/search?q=不存在的关键词")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_search_with_match(client: TestClient, monkeypatch):
    _populate_news_store(
        monkeypatch,
        [
            {"news_id": "n1", "title": "人工智能突破", "summary": "", "content": "", "source": "cls-hot", "url": "u1"},
            {"news_id": "n2", "title": "其他新闻", "summary": "", "content": "", "source": "rss-x", "url": "u2"},
        ],
    )
    resp = client.get("/api/agent/search?q=人工智能")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["news_id"] == "n1"


def test_search_with_source_filter(client: TestClient, monkeypatch):
    _populate_news_store(
        monkeypatch,
        [
            {"news_id": "n1", "title": "人工智能A", "summary": "", "content": "", "source": "cls-hot", "url": "u1"},
            {"news_id": "n2", "title": "人工智能B", "summary": "", "content": "", "source": "rss-x", "url": "u2"},
        ],
    )
    resp = client.get("/api/agent/search?q=人工智能&source=cls-hot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["news_id"] == "n1"


# ── /api/agent/compare ──


def test_compare_empty_keyword_returns_400(client: TestClient, monkeypatch):
    _populate_news_store(monkeypatch, [])
    resp = client.post("/api/agent/compare", json={"keyword": "  "})
    assert resp.status_code == 400


def test_compare_no_match_returns_message(client: TestClient, monkeypatch):
    _populate_news_store(
        monkeypatch,
        [{"news_id": "n1", "title": "无关标题", "summary": "", "source": "s", "url": "u"}],
    )
    resp = client.post("/api/agent/compare", json={"keyword": "不存在"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["matched_count"] == 0
    assert "未找到" in data["comparison"]


def test_compare_with_sources_filter(client: TestClient, monkeypatch):
    """compare 命中后走真实 LLM，这里用 fake interpreter 替换 NewsInterpreter 避免真实调用。"""
    _populate_news_store(
        monkeypatch,
        [
            {"news_id": "n1", "title": "人工智能X", "summary": "", "source": "cls-hot", "url": "u1"},
            {"news_id": "n2", "title": "人工智能Y", "summary": "", "source": "rss-x", "url": "u2"},
        ],
    )

    class _FakeLLM:
        async def ainvoke(self, messages):
            class _R:
                content = "对比分析结果"

            return _R()

    class _FakeInterpreter:
        def __init__(self, mock=False):
            self.llm = _FakeLLM()

    import api.agent as agent_mod

    monkeypatch.setattr(agent_mod, "NewsInterpreter", _FakeInterpreter)

    resp = client.post("/api/agent/compare", json={"keyword": "人工智能", "sources": ["cls-hot"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["keyword"] == "人工智能"
    assert data["matched_count"] == 1  # 只 cls-hot 命中
    assert data["comparison"] == "对比分析结果"


# ── /api/agent/execute ──


def test_execute_refresh_news_mocked(client: TestClient, monkeypatch):
    """execute refresh_news：mock 爬虫返回空，清空+重灌空。"""
    import api.crawlers as crawlers

    monkeypatch.setattr(deps.kw_filter, "enabled", False)

    async def _empty():
        return {}

    monkeypatch.setattr(crawlers.newsnow_batch, "crawl_all", _empty)
    monkeypatch.setattr(crawlers.rss_batch, "crawl_all", _empty)
    # 预置一条旧新闻，验证 refresh 清空语义
    deps.news_store.clear()
    deps.news_store.append(
        {
            "news_id": "old",
            "title": "t",
            "summary": "s",
            "source": "cls-hot",
            "url": "u",
            "content": "",
            "published_at": "2024-01-01",
            "extra": {},
        }
    )

    resp = client.post("/api/agent/execute", json={"action": "refresh_news"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["total_news"] == 0
    # 缓存被清空+重灌空
    assert deps.news_store == []


def test_execute_refresh_source_unknown(client: TestClient, monkeypatch):
    resp = client.post("/api/agent/execute", json={"action": "refresh_source", "source": "nope"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "Unknown source" in data["error"]


def test_execute_refresh_source_missing_source(client: TestClient, monkeypatch):
    resp = client.post("/api/agent/execute", json={"action": "refresh_source"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "source is required" in data["error"]


def test_execute_unknown_action(client: TestClient, monkeypatch):
    resp = client.post("/api/agent/execute", json={"action": "bogus"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "Unknown action" in data["error"]


# ── _create_tools 工具函数（直接调用，不启动 Agent）──


def _make_tools(current_news_id=None, selected_news_ids=None):
    """构建 agent 工具列表（dict 形式便于按 name 取）。"""
    from api.agent import _create_tools

    tools = _create_tools(current_news_id, selected_news_ids or [])
    return {t.name: t for t in tools}


def test_create_tools_returns_expected_tool_names():
    tools = _make_tools()
    expected = {
        "refresh_news",
        "refresh_source",
        "get_trends",
        "search_news",
        "compare_sources",
        "get_news_content",
        "get_briefing_data",
        "search_knowledge_base",
        "generate_article",
        "interpret_news",
    }
    assert expected.issubset(set(tools.keys()))


async def test_tool_get_trends_empty_store():
    """get_trends 工具：空 store 返回提示。"""
    stores.news_store.clear()
    tools = _make_tools()
    result = await tools["get_trends"].ainvoke({"top_n": 5})
    assert "没有新闻数据" in result


async def test_tool_get_trends_with_news():
    stores.news_store.clear()
    stores.news_store.extend(
        [
            {"news_id": "n1", "title": "人工智能突破", "summary": "半导体", "source": "cls-hot", "url": "u"},
            {"news_id": "n2", "title": "人工智能应用", "summary": "ai", "source": "rss-x", "url": "u2"},
        ]
    )
    tools = _make_tools()
    result = await tools["get_trends"].ainvoke({"top_n": 3})
    assert "人工智能" in result or "total_news" in result


async def test_tool_search_news_no_match():
    stores.news_store.clear()
    stores.news_store.extend(
        [{"news_id": "n1", "title": "无关", "summary": "", "content": "", "source": "s", "url": "u"}]
    )
    tools = _make_tools()
    result = await tools["search_news"].ainvoke({"keyword": "不存在"})
    assert "未找到" in result


async def test_tool_search_news_with_match():
    stores.news_store.clear()
    stores.news_store.extend(
        [
            {"news_id": "n1", "title": "人工智能新闻", "summary": "", "content": "", "source": "s", "url": "u"},
            {"news_id": "n2", "title": "其他", "summary": "", "content": "", "source": "s2", "url": "u2"},
        ]
    )
    tools = _make_tools()
    result = await tools["search_news"].ainvoke({"keyword": "人工智能"})
    assert "人工智能新闻" in result


async def test_tool_compare_sources_no_match():
    stores.news_store.clear()
    stores.news_store.extend([{"news_id": "n1", "title": "无关", "summary": "", "source": "s", "url": "u"}])
    tools = _make_tools()
    result = await tools["compare_sources"].ainvoke({"keyword": "不存在"})
    assert "未找到" in result


async def test_tool_compare_sources_with_match():
    stores.news_store.clear()
    stores.news_store.extend(
        [
            {"news_id": "n1", "title": "人工智能X", "summary": "", "source": "cls-hot", "url": "u1"},
            {"news_id": "n2", "title": "人工智能Y", "summary": "", "source": "rss-x", "url": "u2"},
        ]
    )
    tools = _make_tools()
    result = await tools["compare_sources"].ainvoke({"keyword": "人工智能"})
    assert "matched_count" in result


async def test_tool_get_news_content_no_selected():
    """无选中新闻时 get_news_content 返回提示。"""
    tools = _make_tools(current_news_id=None, selected_news_ids=[])
    result = await tools["get_news_content"].ainvoke({})
    assert "没有选中" in result


async def test_tool_get_news_content_with_id(client, monkeypatch):
    """有 current_news_id 时 get_news_content 返回内容（mock ensure_content）。"""
    import database as db

    async def _noop(item):
        return None

    monkeypatch.setattr(deps, "ensure_content", _noop)
    await db.upsert_news(
        [
            {
                "news_id": "n1",
                "title": "标题",
                "summary": "摘要",
                "content": "正文",
                "source": "cls-hot",
                "url": "u",
                "published_at": "2024-01-01",
                "extra": {},
            }
        ]
    )
    tools = _make_tools(current_news_id="n1")
    result = await tools["get_news_content"].ainvoke({})
    assert "标题" in result
    assert "正文" in result


async def test_tool_get_briefing_data_empty():
    stores.news_store.clear()
    tools = _make_tools()
    result = await tools["get_briefing_data"].ainvoke({})
    assert "没有新闻数据" in result


async def test_tool_get_briefing_data_with_news():
    stores.news_store.clear()
    stores.news_store.extend(
        [
            {"news_id": "n1", "title": "标题A", "summary": "摘要A", "source": "cls-hot", "url": "u"},
            {"news_id": "n2", "title": "标题B", "summary": "摘要B", "source": "rss-x", "url": "u2"},
        ]
    )
    tools = _make_tools()
    result = await tools["get_briefing_data"].ainvoke({})
    assert "标题A" in result
    assert "total_news" in result


async def test_tool_refresh_source_unknown():
    """refresh_source 工具：未知 source 返回提示。"""
    tools = _make_tools()
    result = await tools["refresh_source"].ainvoke({"source": "nope"})
    assert "未知的新闻源" in result


async def test_tool_generate_article_no_selected():
    tools = _make_tools()
    result = await tools["generate_article"].ainvoke({})
    assert "没有选中" in result


async def test_tool_interpret_news_no_selected():
    tools = _make_tools()
    result = await tools["interpret_news"].ainvoke({})
    assert "没有选中" in result


async def test_tool_refresh_news_mocked(client, monkeypatch):
    """refresh_news 工具：清空 DB + 重灌 + 失效缓存。"""
    import api.crawlers as crawlers
    import database as db

    monkeypatch.setattr(deps.kw_filter, "enabled", False)

    async def _empty():
        return {}

    monkeypatch.setattr(crawlers.newsnow_batch, "crawl_all", _empty)
    monkeypatch.setattr(crawlers.rss_batch, "crawl_all", _empty)
    # 预置旧数据
    await db.upsert_news(
        [
            {
                "news_id": "old",
                "title": "t",
                "summary": "s",
                "content": "",
                "source": "cls-hot",
                "url": "u",
                "published_at": "2024-01-01",
                "extra": {},
            }
        ]
    )
    stores.news_store.extend(await db.load_news())

    tools = _make_tools()
    result = await tools["refresh_news"].ainvoke({})
    assert "total_news" in result
    # 旧数据被清空
    assert await db.get_news("old") is None
    assert stores.news_store == []
