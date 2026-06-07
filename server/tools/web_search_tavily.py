"""联网搜索工具 - 基于 Tavily Search API。

使用 tavily-python SDK 实现，一次 API 调用即可返回搜索结果，
比 Kimi $web_search 更快（无需两次调用）。

Tavily 专为 AI Agent 设计，返回结构化搜索结果，免费额度 1000 次/月。
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def web_search(query: str) -> str:
    """联网搜索互联网获取最新信息。当用户的问题需要实时互联网数据、
    本地新闻库中没有相关信息时调用此工具。支持搜索任何话题的最新信息。
    返回基于搜索结果整理的摘要内容。"""
    from tavily import AsyncTavilyClient
    from config import TAVILY_API_KEY

    try:
        client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
        logger.info("Tavily search: query=%s", query)

        response = await client.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_raw_content=False,
        )

        # response 是 dict，包含 "results" 列表
        results = response.get("results", [])
        if not results:
            return "搜索未返回结果。"

        # 格式化搜索结果
        formatted = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("url", "")
            content = r.get("content", "")
            formatted.append(f"### {i}. {title}\n来源: {url}\n{content}")

        result_text = "\n\n".join(formatted)
        logger.info("Tavily search: got %d results, total length=%d", len(results), len(result_text))
        return result_text

    except Exception as e:
        logger.exception("Tavily search failed: %s", e)
        return f"联网搜索失败：{e}"
