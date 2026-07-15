"""联网搜索工具测试：_parse_kimi_structured 解析、get_web_search_tool 配置门控、
web_search_structured 调度逻辑（mock 外部 API，离线）。
"""

from __future__ import annotations

from tools import web_search

# ── _parse_kimi_structured 纯函数解析 ──


def test_parse_kimi_structured_empty_returns_empty():
    assert web_search._parse_kimi_structured("") == []


def test_parse_kimi_structured_strict_format():
    """严格 `### n. title\\n来源: url\\ncontent` 格式解析。"""
    text = (
        "### 1. 标题一\n来源: https://a.com/1\n内容一第一段。\n\n内容一第二段。\n\n"
        "### 2. 标题二\n来源: https://a.com/2\n内容二。"
    )
    result = web_search._parse_kimi_structured(text)
    assert len(result) == 2
    assert result[0]["title"] == "标题一"
    assert result[0]["url"] == "https://a.com/1"
    assert "内容一第一段" in result[0]["content"]
    assert result[1]["title"] == "标题二"
    assert result[1]["url"] == "https://a.com/2"


def test_parse_kimi_structured_fallback_markdown_links():
    """无严格格式但有 markdown 链接时回退抽取。"""
    text = "这是一些文字。[示例链接](https://b.com) 后续内容。"
    result = web_search._parse_kimi_structured(text)
    assert len(result) == 1
    assert result[0]["url"] == "https://b.com"
    assert result[0]["title"] == "示例链接"
    assert "后续内容" in result[0]["content"]


def test_parse_kimi_structured_fallback_bare_url():
    """仅有裸 URL 时回退抽取，title 用 URL。"""
    text = "https://c.com/page\n其他无结构文本"
    result = web_search._parse_kimi_structured(text)
    # 至少回退到裸 URL 或终极兜底
    assert len(result) >= 1
    assert any(r["url"] == "https://c.com/page" or "https://c.com/page" in r.get("content", "") for r in result)


def test_parse_kimi_structured_ultimate_fallback_free_text():
    """无结构化标记也无链接的自由长文，保留为一条结果。"""
    text = "## 某个标题\n这是一段较长的自由文本内容，没有任何结构化标记或链接。"
    result = web_search._parse_kimi_structured(text)
    assert len(result) == 1
    assert result[0]["content"] == text.strip()
    # title 取首个非空行（去掉 markdown 标题符号）
    assert result[0]["title"] == "某个标题"


# ── get_web_search_tool 配置门控 ──


def test_get_web_search_tool_disabled_returns_none(monkeypatch):
    """WEB_SEARCH_ENABLED=False 返回 None。"""
    monkeypatch.setattr("config.WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr("config.WEB_SEARCH_ENGINE", "kimi")
    monkeypatch.setattr("config.MOONSHOT_API_KEY", "dummy")
    assert web_search.get_web_search_tool() is None


def test_get_web_search_tool_kimi_without_key_returns_none(monkeypatch):
    """kimi 引擎但无 MOONSHOT_API_KEY 返回 None。"""
    monkeypatch.setattr("config.WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr("config.WEB_SEARCH_ENGINE", "kimi")
    monkeypatch.setattr("config.MOONSHOT_API_KEY", "")
    assert web_search.get_web_search_tool() is None


def test_get_web_search_tool_kimi_with_key_returns_tool(monkeypatch):
    """kimi 引擎且有 key 返回 web_search tool。"""
    monkeypatch.setattr("config.WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr("config.WEB_SEARCH_ENGINE", "kimi")
    monkeypatch.setattr("config.MOONSHOT_API_KEY", "dummy")
    tool = web_search.get_web_search_tool()
    assert tool is not None


def test_get_web_search_tool_tavily_without_key_returns_none(monkeypatch):
    """tavily 引擎但无 TAVILY_API_KEY 返回 None。"""
    monkeypatch.setattr("config.WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr("config.WEB_SEARCH_ENGINE", "tavily")
    monkeypatch.setattr("config.TAVILY_API_KEY", "")
    assert web_search.get_web_search_tool() is None


def test_get_web_search_tool_tavily_with_key_returns_tool(monkeypatch):
    """tavily 引擎且有 key 返回 web_search tool。"""
    monkeypatch.setattr("config.WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr("config.WEB_SEARCH_ENGINE", "tavily")
    monkeypatch.setattr("config.TAVILY_API_KEY", "dummy")
    tool = web_search.get_web_search_tool()
    assert tool is not None


# ── web_search_structured 调度（mock 外部 API）──


async def test_web_search_structured_tavily(monkeypatch):
    """tavily 引擎：直接取 results 字段。"""
    monkeypatch.setattr("config.WEB_SEARCH_ENGINE", "tavily")
    monkeypatch.setattr("config.TAVILY_API_KEY", "dummy")

    fake_response = {
        "results": [
            {"title": "结果1", "url": "https://t.com/1", "content": "内容1"},
            {"title": "结果2", "url": "https://t.com/2", "content": "内容2"},
        ]
    }

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def search(self, **kwargs):
            return fake_response

    monkeypatch.setattr("tools.web_search.AsyncTavilyClient", _FakeClient, raising=False)
    # web_search_structured 内部 `from tavily import AsyncTavilyClient`，patch 模块属性

    monkeypatch.setattr("tavily.AsyncTavilyClient", _FakeClient)

    result = await web_search.web_search_structured("query")
    assert len(result) == 2
    assert result[0]["title"] == "结果1"
    assert result[1]["url"] == "https://t.com/2"


async def test_web_search_structured_kimi_parses_text(monkeypatch):
    """kimi 引擎：调 web_search_kimi 再 _parse_kimi_structured。"""
    monkeypatch.setattr("config.WEB_SEARCH_ENGINE", "kimi")

    kimi_text = (
        "### 1. 标题A\n来源: https://k.com/1\n内容A。\n\n"
        "### 2. 标题B\n来源: https://k.com/2\n内容B。"
    )

    class _FakeKimiTool:
        async def ainvoke(self, args):  # noqa: ARG002
            return kimi_text

    # web_search_structured 内部 `from tools.web_search_kimi import web_search_kimi`，
    # 替换模块级 tool 对象为可调用 stub。
    import tools.web_search_kimi as kimi_mod

    monkeypatch.setattr(kimi_mod, "web_search_kimi", _FakeKimiTool())

    result = await web_search.web_search_structured("query")
    assert len(result) == 2
    assert result[0]["title"] == "标题A"
    assert result[1]["url"] == "https://k.com/2"
