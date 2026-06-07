"""联网搜索工具 - 统一路由入口。

根据 WEB_SEARCH_ENGINE 配置分发到不同搜索引擎实现：
- kimi: 基于 Kimi $web_search（需要 MOONSHOT_API_KEY）
- tavily: 基于 Tavily Search API（需要 TAVILY_API_KEY）
"""

from __future__ import annotations

import logging

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
