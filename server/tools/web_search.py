"""联网搜索工具 - 统一路由入口。

根据 WEB_SEARCH_ENGINE 配置分发到不同搜索引擎实现：
- kimi: 基于 Kimi $web_search（需要 MOONSHOT_API_KEY）
- tavily: 基于 Tavily Search API（需要 TAVILY_API_KEY）
"""

from __future__ import annotations

import logging
import re

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def web_search(query: str) -> str:
    """联网搜索互联网获取最新信息。当用户的问题需要实时互联网数据、
    本地新闻库中没有相关信息时调用此工具。支持搜索任何话题的最新信息。
    返回基于搜索结果整理的摘要内容。"""
    from config import WEB_SEARCH_ENGINE

    engine = (WEB_SEARCH_ENGINE or "kimi").lower()

    if engine == "tavily":
        from tools.web_search_tavily import web_search as tavily_search
        return await tavily_search.ainvoke({"query": query})
    else:
        from tools.web_search_kimi import web_search_kimi as kimi_search
        return await kimi_search.ainvoke({"query": query})


async def web_search_structured(query: str) -> list[dict]:
    """联网搜索并返回结构化结果列表 [{title, url, content}]。

    Tavily 路径直接取原始 results；Kimi 路径返回合成文本，
    按 `### n. title\n来源: url\ncontent` 格式解析回结构化。
    """
    from config import WEB_SEARCH_ENGINE

    engine = (WEB_SEARCH_ENGINE or "kimi").lower()

    if engine == "tavily":
        from tavily import AsyncTavilyClient
        from config import TAVILY_API_KEY

        client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
        response = await client.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_raw_content=False,
        )
        results = response.get("results", []) or []
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            }
            for r in results
        ]

    # Kimi 路径：返回合成文本，需解析回结构化
    from tools.web_search_kimi import web_search_kimi as kimi_search
    text = await kimi_search.ainvoke({"query": query})
    return _parse_kimi_structured(text)


_KIMI_RESULT_RE = re.compile(
    r"###\s*\d+\.\s*(?P<title>[^\n]*)\n\s*来源[:：]\s*(?P<url>\S[^\n]*)\n(?P<content>(?:(?!###\s*\d+\.).)*)",
    re.DOTALL,
)

# 兜底：从纯文本/任意 markdown 中抽取链接作为结果（[title](url) 或裸 url）
_KIMI_MD_LINK_RE = re.compile(r"\[(?P<title>[^\]]+)\]\((?P<url>https?://[^\s)]+)\)")
_KIMI_BARE_URL_RE = re.compile(r"(?m)^(?P<url>https?://[^\s)]+)\s*$")


def _parse_kimi_structured(text: str) -> list[dict]:
    """解析 Kimi 合成的 markdown 搜索结果为结构化列表。

    优先按 `### n. title\\n来源: url\\ncontent` 严格格式解析；
    若 Kimi 返回的是自由 markdown，则回退抽取其中的链接与段落。
    """
    if not text:
        return []
    items: list[dict] = []
    for m in _KIMI_RESULT_RE.finditer(text):
        items.append(
            {
                "title": m.group("title").strip(),
                "url": m.group("url").strip(),
                "content": m.group("content").strip(),
            }
        )
    if items:
        return items

    # 回退：按 markdown 链接 + 其后续段落抽取
    fallback: list[dict] = []
    for m in _KIMI_MD_LINK_RE.finditer(text):
        title = m.group("title").strip()
        url = m.group("url").strip()
        # 取该链接之后到下一个链接之前的文本作为 content
        start = m.end()
        nxt = _KIMI_MD_LINK_RE.search(text, start)
        end = nxt.start() if nxt else len(text)
        content = text[start:end].strip()
        fallback.append({"title": title or url, "url": url, "content": content})
    if fallback:
        return fallback

    # 最后兜底：仅抽裸 URL，title 用 URL 本身
    for m in _KIMI_BARE_URL_RE.finditer(text):
        fallback.append({"title": m.group("url"), "url": m.group("url"), "content": ""})
    if fallback:
        return fallback

    # 终极兜底：Kimi 返回的是自由长文（无结构化标记也无链接），
    # 仍保留为一条结果，保证知识库界面有内容可入库而非“未搜索到结果”。
    # title 取首个非空行（去掉 markdown 标题符号）；url 留空。
    stripped = text.strip()
    if stripped:
        first_line = ""
        for line in stripped.splitlines():
            t = line.strip().lstrip("#").strip()
            if t:
                first_line = t
                break
        fallback.append({
            "title": first_line or "联网搜索结果",
            "url": "",
            "content": stripped,
        })
    return fallback


def get_web_search_tool():
    """返回配置可用的联网搜索工具，如果未配置则返回 None。"""
    from config import WEB_SEARCH_ENABLED, WEB_SEARCH_ENGINE, MOONSHOT_API_KEY, TAVILY_API_KEY

    if not WEB_SEARCH_ENABLED:
        return None

    engine = (WEB_SEARCH_ENGINE or "kimi").lower()

    if engine == "tavily":
        if TAVILY_API_KEY:
            logger.info("Web search engine: Tavily")
            return web_search
        else:
            logger.warning("WEB_SEARCH_ENGINE=tavily but TAVILY_API_KEY not set")
            return None
    else:
        if MOONSHOT_API_KEY:
            logger.info("Web search engine: Kimi")
            return web_search
        else:
            logger.warning("WEB_SEARCH_ENGINE=kimi but MOONSHOT_API_KEY not set")
            return None
