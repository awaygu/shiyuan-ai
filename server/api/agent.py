"""Agent smart API routes: chat with function calling, execute, trends, compare, search, briefing."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import NEWS_SOURCES
from . import deps
from .interpret import LIMITED_CONTENT_MSG
from core.interpreter import NewsInterpreter
from core.style_manager import StyleType, prompt_manager, build_prompt_display_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])


# ── Keyword Extraction ─────────────────────────────────────────

def _extract_keywords(text: str, top_n: int = 30) -> list[tuple[str, int]]:
    """Extract top keywords from text using simple N-gram frequency."""
    stop_words = {
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
        "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
        "看", "好", "自己", "这", "他", "她", "它", "们", "那", "被", "从", "把",
        "对", "与", "为", "而", "或", "但", "如果", "因为", "所以", "可以", "已经",
        "将", "让", "被", "还", "又", "等", "之", "中", "其", "所", "以", "于",
        "及", "更", "最", "该", "此", "每", "各", "同", "则", "此", "该",
        "日电", "亿元", "万元", "公司", "市场", "目前", "相关", "情况", "方面",
        "今日", "报道", "消息", "数据显示", "财联社",
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "and", "but", "or",
        "not", "no", "nor", "so", "if", "than", "too", "very", "just",
        "https", "http", "com", "url", "www", "article", "comments",
        "how", "its", "new", "use", "using", "about", "your", "more",
        "all", "also", "one", "our", "out", "up", "own", "any", "some",
        "which", "their", "there", "than", "then", "only", "other", "over",
        "such", "what", "when", "who", "will", "self", "hosted", "points",
        "show", "daily", "post", "home", "like", "well", "into", "made",
    }

    cleaned = re.sub(r'https?://\S+', '', text)
    cleaned = re.sub(r'\bArticle URL:\b|\bComments URL:\b', '', cleaned)

    words = re.findall(r'[\u4e00-\u9fff]{2,6}|[a-zA-Z]{4,}', cleaned.lower())
    filtered = [w for w in words if w not in stop_words]
    return Counter(filtered).most_common(top_n)


# ── Tool Definitions ──────────────────────────────────────────

TOOL_DISPLAY_NAMES = {
    "refresh_news": "刷新新闻",
    "refresh_source": "刷新新闻源",
    "get_trends": "获取热点",
    "search_news": "搜索新闻",
    "compare_sources": "对比分析",
    "get_news_content": "获取新闻内容",
    "get_briefing_data": "获取简报数据",
    "search_knowledge_base": "搜索知识库",
    "web_search": "联网搜索",
    "generate_article": "生成文章",
    "interpret_news": "解读新闻",
}


def _create_tools(current_news_id: str | None, selected_news_ids: list[str]):
    """Create LangChain tool functions with request-scoped context."""
    from langchain_core.tools import tool

    @tool
    async def refresh_news() -> str:
        """重新爬取所有新闻源，获取最新新闻。当用户要求刷新、更新新闻时调用。"""
        async with deps.news_lock:
            deps.news_store = []
            all_raw: list = []
            results = {}
            try:
                newsnow_results = await deps.newsnow_batch.crawl_all()
                for platform_id, items in newsnow_results.items():
                    all_raw.extend(items)
                    results[f"newsnow_{platform_id}"] = len(items)
            except Exception as e:
                results["newsnow_error"] = str(e)
            try:
                rss_results = await deps.rss_batch.crawl_all()
                for feed_id, items in rss_results.items():
                    all_raw.extend(items)
                    results[f"rss_{feed_id}"] = len(items)
            except Exception as e:
                results["rss_error"] = str(e)
            filtered = deps.kw_filter.filter_newsitems(all_raw)
            for item in filtered:
                deps.news_store.append(item.to_dict())
            await deps.save_news(deps.news_store)
        return json.dumps({
            "total_news": len(deps.news_store),
            "source_results": results,
        }, ensure_ascii=False)

    @tool
    async def refresh_source(source: str) -> str:
        """刷新指定的新闻源。source 为新闻源 ID，如 cls-telegraph, toutiao, hacker-news 等。"""
        if source in deps.NEWSNOW_CRAWLERS:
            crawler = deps.NEWSNOW_CRAWLERS[source]
            items = await crawler.crawl()
        elif any(feed.id == source for feed in deps.DEFAULT_RSS_FEEDS):
            feed = next(f for f in deps.DEFAULT_RSS_FEEDS if f.id == source)
            from crawlers.rss import RSSCrawler
            crawler = RSSCrawler(feed)
            items = await crawler.crawl()
        else:
            available = list(deps.NEWSNOW_CRAWLERS.keys()) + [f.id for f in deps.DEFAULT_RSS_FEEDS]
            return f"未知的新闻源: {source}。可用源: {', '.join(available)}"
        async with deps.news_lock:
            filtered = deps.kw_filter.filter_newsitems(items)
            new_count = 0
            for item in filtered:
                item_dict = item.to_dict()
                if not any(n["news_id"] == item_dict["news_id"] for n in deps.news_store):
                    deps.news_store.append(item_dict)
                    new_count += 1
            await deps.save_news(deps.news_store)
        return json.dumps({"source": source, "total": len(items), "new": new_count}, ensure_ascii=False)

    @tool
    async def get_trends(top_n: int = 10) -> str:
        """获取当前热门话题和关键词趋势。当用户问热点、趋势、热门话题时调用。"""
        if not deps.news_store:
            return "当前没有新闻数据，请先调用 refresh_news 刷新新闻。"

        all_text = " ".join(
            f"{n.get('title', '')} {n.get('summary', '')}"
            for n in deps.news_store
        )
        keywords = _extract_keywords(all_text, top_n=top_n * 3)

        trends = []
        for kw, count in keywords[:top_n]:
            related = [
                {"title": n.get("title", ""), "source": n.get("source", "")}
                for n in deps.news_store
                if kw in f"{n.get('title', '')} {n.get('summary', '')}".lower()
            ]
            sources = set(n.get("source", "") for n in related)
            trends.append({
                "keyword": kw,
                "count": count,
                "source_count": len(sources),
                "related_titles": [r["title"] for r in related[:3]],
            })

        return json.dumps({
            "total_news": len(deps.news_store),
            "trends": trends,
        }, ensure_ascii=False)

    @tool
    async def search_news(keyword: str) -> str:
        """根据关键词搜索新闻。当用户要搜索、查找特定话题的新闻时调用。"""
        kw = keyword.lower().strip()
        results = [
            n for n in deps.news_store
            if kw in f"{n.get('title', '')} {n.get('summary', '')} {n.get('content', '')}".lower()
        ]
        if not results:
            return f"未找到与「{keyword}」相关的新闻。"

        items = []
        for n in results[:15]:
            items.append({"title": n.get("title", ""), "source": n.get("source", ""), "url": n.get("url", "")})

        return json.dumps({"keyword": keyword, "total": len(results), "items": items}, ensure_ascii=False)

    @tool
    async def compare_sources(keyword: str) -> str:
        """对比不同新闻源对同一话题的报道。当用户要求对比、比较不同媒体的观点时调用。返回各来源相关新闻供你分析差异。"""
        kw = keyword.lower().strip()
        matched = [
            n for n in deps.news_store
            if kw in f"{n.get('title', '')} {n.get('summary', '')}".lower()
        ]
        if not matched:
            return f"未找到与「{keyword}」相关的新闻。"

        by_source: dict[str, list] = {}
        for n in matched:
            src = n.get("source", "")
            src_label = NEWS_SOURCES.get(src, src)
            by_source.setdefault(src_label, []).append(n.get("title", ""))

        sections = []
        for src_label, titles in by_source.items():
            titles_text = "\n".join(f"- {t}" for t in titles[:5])
            sections.append(f"### {src_label}（{len(titles)} 条）\n{titles_text}")

        return json.dumps({
            "keyword": keyword,
            "matched_count": len(matched),
            "sources": list(by_source.keys()),
            "by_source": sections,
        }, ensure_ascii=False)

    @tool
    async def get_news_content() -> str:
        """获取当前选中或正在查看的新闻的完整内容。当用户要求解读、分析新闻时先调用此工具获取内容。"""
        ids = selected_news_ids or ([current_news_id] if current_news_id else [])
        if not ids:
            return "当前没有选中或查看的新闻。请告知用户先选择一条新闻。"

        results = []
        for nid in ids:
            item = deps.find_news(nid)
            if item:
                await deps.ensure_content(item)
                title = item.get("title", "")
                source = item.get("source", "")
                content = item.get("content", item.get("summary", ""))
                results.append(f"## {title}\n来源: {source}\n\n{content}")

        return "\n\n---\n\n".join(results) if results else "未找到新闻内容。"

    @tool
    async def get_briefing_data() -> str:
        """获取今日要闻简报所需的新闻数据汇总。当用户要求生成简报、今日要闻时先调用此工具获取数据。"""
        if not deps.news_store:
            return "当前没有新闻数据，请先调用 refresh_news 刷新新闻。"

        by_source: dict[str, list] = {}
        for n in deps.news_store:
            src = n.get("source", "")
            src_label = NEWS_SOURCES.get(src, src)
            by_source.setdefault(src_label, []).append({
                "title": n.get("title", ""),
                "summary": n.get("summary", ""),
            })

        sections = []
        for src_label, items in by_source.items():
            lines = []
            for i in items[:8]:
                line = f"- {i['title']}"
                if i["summary"] and i["summary"] != i["title"]:
                    line += f"：{i['summary'][:80]}"
                lines.append(line)
            sections.append(f"### {src_label}（{len(items)} 条）\n" + "\n".join(lines))

        return json.dumps({
            "total_news": len(deps.news_store),
            "sources": len(by_source),
            "data": "\n\n".join(sections),
        }, ensure_ascii=False)

    @tool
    async def search_knowledge_base(query: str, top_k: int = 5) -> str:
        """搜索用户上传的知识库文档，查找与查询最相关的文档片段。当用户提到知识库、文档、资料、上传的文件等内容时调用此工具。"""
        from api.knowledge import kb_search_internal
        return await kb_search_internal(query, top_k)

    @tool
    async def generate_article(style: str = "wechat_mp", title: str | None = None, prompt: str | None = None) -> str:
        """根据当前选中的新闻生成自媒体文章。当用户要求写文章、生成内容、创作帖子时调用此工具。
        style 可选: xiaohongshu（小红书）、wechat_mp（微信公众号）、douyin（抖音），默认 wechat_mp。
        title 为可选自定义标题，prompt 为可选自定义提示词。
        此工具会自动获取新闻内容并按风格生成，无需先调用 get_news_content。"""
        ids = selected_news_ids or ([current_news_id] if current_news_id else [])
        if not ids:
            return "当前没有选中或查看的新闻。请告知用户先选择一条新闻。"

        items = deps.find_news_batch(ids)
        if not items:
            return "未找到对应的新闻内容。"

        for item in items:
            await deps.ensure_content(item)

        limited = [item.get("title", "") for item in items if deps.is_limited_content(item)]
        if limited and not any(not deps.is_limited_content(i) for i in items):
            return LIMITED_CONTENT_MSG

        resolved_style = deps.resolve_style(style)
        article = await deps.interpreter.generate_article(items, resolved_style, title, prompt=prompt)
        article["article_id"] = f"art_{uuid4().hex[:12]}"

        async with deps.article_lock:
            deps.article_store.append(article)
            await deps.save_article(article)

        return json.dumps({
            "article_id": article["article_id"],
            "title": article.get("title", ""),
            "style": resolved_style.value,
            "content_length": len(article.get("content", "")),
            "message": "文章已生成，article_id 已保存，可用于发布。",
        }, ensure_ascii=False)

    @tool
    async def interpret_news() -> str:
        """对当前选中的新闻进行深度解读分析。当用户要求解读、分析新闻时调用此工具。
        此工具会自动获取新闻内容并进行解读，无需先调用 get_news_content。"""
        ids = selected_news_ids or ([current_news_id] if current_news_id else [])
        if not ids:
            return "当前没有选中或查看的新闻。请告知用户先选择一条新闻。"

        items = deps.find_news_batch(ids)
        if not items:
            return "未找到对应的新闻内容。"

        for item in items:
            await deps.ensure_content(item)

        limited = [item.get("title", "") for item in items if deps.is_limited_content(item)]
        if limited and not any(not deps.is_limited_content(i) for i in items):
            return LIMITED_CONTENT_MSG

        style = deps.resolve_style("wechat_mp")
        result = await deps.interpreter.interpret(items, style)
        return result

    tools_list = [refresh_news, refresh_source, get_trends, search_news, compare_sources, get_news_content, get_briefing_data, search_knowledge_base, generate_article, interpret_news]

    # 联网搜索工具（根据 WEB_SEARCH_ENGINE 配置选择引擎）
    from tools.web_search import get_web_search_tool
    web_search_tool = get_web_search_tool()
    if web_search_tool:
        tools_list.append(web_search_tool)

    return tools_list


# ── Trends (standalone endpoint for action bar) ────────────────

@router.get("/trends")
async def get_trends(top_n: int = Query(10, ge=1, le=50)):
    """Get trending topics from recent news using keyword frequency."""
    if not deps.news_store:
        return {"trends": [], "total_news": 0}

    all_text = " ".join(
        f"{n.get('title', '')} {n.get('summary', '')}"
        for n in deps.news_store
    )

    keywords = _extract_keywords(all_text, top_n=top_n * 3)

    trends = []
    for kw, count in keywords[:top_n]:
        related = [
            {
                "news_id": n.get("news_id", ""),
                "title": n.get("title", ""),
                "source": n.get("source", ""),
                "url": n.get("url", ""),
            }
            for n in deps.news_store
            if kw in f"{n.get('title', '')} {n.get('summary', '')}".lower()
        ]

        sources = set(n.get("source", "") for n in related)
        trends.append({
            "keyword": kw,
            "count": count,
            "source_count": len(sources),
            "related_news": related[:5],
        })

    return {"trends": trends, "total_news": len(deps.news_store)}


# ── Compare (standalone endpoint for action bar) ───────────────

class CompareRequest(BaseModel):
    keyword: str
    sources: list[str] | None = None


@router.post("/compare")
async def compare_sources(req: CompareRequest):
    """Compare coverage of a topic across different sources using LLM."""
    keyword = req.keyword.strip()
    if not keyword:
        raise HTTPException(400, "keyword is required")

    matched = [
        n for n in deps.news_store
        if keyword.lower() in f"{n.get('title', '')} {n.get('summary', '')}".lower()
    ]

    if req.sources:
        matched = [n for n in matched if n.get("source") in req.sources]

    if not matched:
        return {"keyword": keyword, "comparison": f"未找到与「{keyword}」相关的新闻。", "matched_count": 0}

    from config import NEWS_SOURCES

    by_source: dict[str, list] = {}
    for n in matched:
        src = n.get("source", "")
        src_label = NEWS_SOURCES.get(src, src)
        by_source.setdefault(src_label, []).append(n)

    source_sections = []
    for src_label, items in by_source.items():
        titles = "\n".join(f"- {i.get('title', '')}" for i in items[:5])
        source_sections.append(f"### {src_label}（{len(items)} 条）\n{titles}")

    sources_text = "\n\n".join(source_sections)

    prompt_text = f"""请比较以下不同媒体对「{keyword}」的报道差异，包括：
1. 各媒体关注角度的差异
2. 报道倾向和侧重点的不同
3. 信息互补之处

## 各来源报道

{sources_text}"""

    interpreter = NewsInterpreter(mock=False)

    from langchain_core.messages import SystemMessage, HumanMessage
    messages = [SystemMessage(content=prompt_manager.get_system_prompt("interpret")), HumanMessage(content=prompt_text)]
    result = await interpreter.llm.ainvoke(messages)

    return {
        "keyword": keyword,
        "comparison": result.content,
        "matched_count": len(matched),
        "sources": list(by_source.keys()),
    }


# ── Search (standalone endpoint for action bar) ────────────────

@router.get("/search")
async def search_news(
    q: str = Query(..., min_length=1),
    source: str | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    """Search news by keyword."""
    keyword = q.lower().strip()

    results = [
        n for n in deps.news_store
        if keyword in f"{n.get('title', '')} {n.get('summary', '')} {n.get('content', '')}".lower()
    ]

    if source:
        results = [n for n in results if n.get("source") == source]

    return {
        "keyword": q,
        "total": len(results),
        "items": results[:limit],
    }


# ── Briefing (standalone SSE endpoint for action bar) ──────────

@router.post("/briefing/stream")
async def briefing_stream():
    """Generate a daily briefing summary via SSE streaming."""
    if not deps.news_store:
        return {"briefing": "当前没有新闻数据，请先爬取新闻。"}

    from config import NEWS_SOURCES

    by_source: dict[str, list] = {}
    for n in deps.news_store:
        src = n.get("source", "")
        src_label = NEWS_SOURCES.get(src, src)
        by_source.setdefault(src_label, []).append(n.get("title", ""))

    source_summaries = []
    for src_label, titles in by_source.items():
        top_titles = "\n".join(f"- {t}" for t in titles[:8])
        source_summaries.append(f"### {src_label}（{len(titles)} 条）\n{top_titles}")

    news_overview = "\n\n".join(source_summaries)

    prompt_text = f"""请基于以下来自多个来源的新闻标题，生成一份今日要闻简报。要求：

1. 用简洁的语言提炼 5-8 个核心要点
2. 按重要性排序
3. 每个要点一句话概括
4. 最后给出一句今日趋势总结

## 今日新闻一览

{news_overview}"""

    interpreter = NewsInterpreter(mock=False)

    async def event_stream():
        meta = json.dumps({
            "type": "meta",
            "total_news": len(deps.news_store),
            "sources": len(by_source),
        }, ensure_ascii=False)
        yield f"data: {meta}\n\n"

        yield f"data: {json.dumps({'type': 'loading', 'message': '正在生成今日简报...'}, ensure_ascii=False)}\n\n"

        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [SystemMessage(content=prompt_manager.get_system_prompt("interpret")), HumanMessage(content=prompt_text)]

        async for chunk in interpreter.llm.astream(messages):
            if chunk.content:
                data = json.dumps({"type": "chunk", "content": chunk.content}, ensure_ascii=False)
                yield f"data: {data}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=deps.SSE_HEADERS,
    )


# ── Agent Chat with Function Calling ──────────────────────────

class AgentChatRequest(BaseModel):
    message: str
    news_ids: list[str] = Field(default_factory=list)
    current_news_id: str | None = None
    web_search: bool = False
    conversation_id: str | None = None


@router.post("/chat/stream")
async def agent_chat_stream(req: AgentChatRequest):
    """Agent chat with LangGraph Agent + SummarizationMiddleware + SQLite checkpointer.

    完全保留现有 SSE 事件格式，前端零改动。
    新增 conversation_id 参数支持多轮对话记忆。
    """
    from core.agent_graph import build_agent
    from core.checkpointer import create_conversation, add_message, get_conversation

    tools = _create_tools(req.current_news_id, req.news_ids)

    # 创建或获取 conversation
    conv_id = req.conversation_id
    is_new_conversation = not conv_id
    if is_new_conversation:
        # 用用户消息前 20 字作为标题
        title = req.message[:20] + ("..." if len(req.message) > 20 else "")
        conv = await asyncio.to_thread(create_conversation, title=title)
        conv_id = conv["id"]

    current_news_text = ""
    if req.current_news_id:
        current_item = deps.find_news(req.current_news_id)
        if current_item:
            await deps.ensure_content(current_item)
            current_news_text = f"\n\n当前用户正在查看的新闻：{current_item.get('title', '')}"

    human = req.message
    if req.news_ids:
        human = f"用户选中的新闻ID: {', '.join(req.news_ids)}\n\n{req.message}"

    # 构建 system prompt
    system_prompt = prompt_manager.agent_system_prompt + current_news_text

    # 构建 Agent
    agent = await build_agent(tools=tools, system_prompt=system_prompt)

    async def event_stream():
        # 发送 conversation_id 事件（前端需要保存到 localStorage）
        yield f"data: {json.dumps({'type': 'conversation_id', 'id': conv_id}, ensure_ascii=False)}\n\n"

        # 当用户开启联网搜索时，先执行搜索，将结果注入上下文
        web_search_result = None
        if req.web_search:
            from tools.web_search import get_web_search_tool
            ws_tool = get_web_search_tool()
            if ws_tool:
                yield f"data: {json.dumps({'type': 'loading', 'message': '正在联网搜索...'}, ensure_ascii=False)}\n\n"
                try:
                    web_search_result = await ws_tool.ainvoke({"query": req.message})
                except Exception as e:
                    logger.exception("Forced web_search failed")
                    web_search_result = f"联网搜索失败：{e}"
            else:
                web_search_result = "联网搜索未启用（未配置 API Key 或未开启 WEB_SEARCH_ENABLED）。"

        # 如果已执行联网搜索，将结果注入用户消息
        if web_search_result is not None:
            enhanced_human = f"{human}\n\n[联网搜索结果]\n{web_search_result}\n\n请基于以上联网搜索结果回答用户的问题。"
        else:
            enhanced_human = human

        # 保存用户消息到数据库
        await asyncio.to_thread(add_message, conv_id, role="user", content=enhanced_human)

        # 发送 prompt 事件
        prompt_text = build_prompt_display_text(system_prompt, enhanced_human)
        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"

        # 调用 LangGraph Agent
        config = {"configurable": {"thread_id": conv_id}}

        try:
            stream = agent.astream_events(
                {"messages": [{"role": "user", "content": enhanced_human}]},
                config,
                version="v2",
            )

            full_response = ""
            current_tool_name = None

            async for event in stream:
                event_kind = event.get("event", "")

                # LLM 输出 token
                if event_kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        if isinstance(chunk.content, str):
                            full_response += chunk.content
                            data = json.dumps({"type": "chunk", "content": chunk.content}, ensure_ascii=False)
                            yield f"data: {data}\n\n"
                        elif isinstance(chunk.content, list):
                            for part in chunk.content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    text = part.get("text", "")
                                    full_response += text
                                    data = json.dumps({"type": "chunk", "content": text}, ensure_ascii=False)
                                    yield f"data: {data}\n\n"

                # 工具开始执行
                elif event_kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
                    current_tool_name = tool_name
                    yield f"data: {json.dumps({'type': 'loading', 'message': f'正在{display_name}...'}, ensure_ascii=False)}\n\n"

                # 工具执行完成
                elif event_kind == "on_tool_end":
                    tool_name = event.get("name", current_tool_name or "")
                    # 工具有前端副作用的发送 action 事件
                    if tool_name in ("refresh_news", "refresh_source"):
                        output = event.get("data", {}).get("output", "")
                        try:
                            args = json.loads(output) if isinstance(output, str) else {}
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        yield f"data: {json.dumps({'type': 'action', 'action': {'action': tool_name, **args}}, ensure_ascii=False)}\n\n"
                    elif tool_name == "generate_article":
                        output = event.get("data", {}).get("output", "")
                        try:
                            args = json.loads(output) if isinstance(output, str) else {}
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        yield f"data: {json.dumps({'type': 'action', 'action': {'action': 'generate_article', **args}}, ensure_ascii=False)}\n\n"
                    current_tool_name = None

            # 保存 AI 回复到数据库
            if full_response:
                await asyncio.to_thread(add_message, conv_id, role="assistant", content=full_response)

        except Exception as e:
            logger.exception("Agent stream failed: %s", e)
            error_msg = f"处理失败：{e}"
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg}, ensure_ascii=False)}\n\n"
            # 保存错误信息到数据库
            await asyncio.to_thread(add_message, conv_id, role="assistant", content=error_msg)

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=deps.SSE_HEADERS,
    )


# ── Execute Site Actions ──────────────────────────────────────

class ExecuteRequest(BaseModel):
    action: str
    source: str | None = None
    keyword: str | None = None
    style: str = "wechat_mp"


@router.post("/execute")
async def execute_action(req: ExecuteRequest):
    """Execute a site action requested by the agent."""
    action = req.action

    if action == "refresh_news":
        async with deps.news_lock:
            deps.news_store = []
            results = {}
            all_raw: list = []
            try:
                newsnow_results = await deps.newsnow_batch.crawl_all()
                for platform_id, items in newsnow_results.items():
                    all_raw.extend(items)
                    results[f"newsnow_{platform_id}"] = {"status": "ok", "count": len(items)}
            except Exception as e:
                results["newsnow"] = {"status": "error", "error": str(e)}
            try:
                rss_results = await deps.rss_batch.crawl_all()
                for feed_id, items in rss_results.items():
                    all_raw.extend(items)
                    results[f"rss_{feed_id}"] = {"status": "ok", "count": len(items)}
            except Exception as e:
                results["rss"] = {"status": "error", "error": str(e)}
            filtered = deps.kw_filter.filter_newsitems(all_raw)
            for item in filtered:
                deps.news_store.append(item.to_dict())
            await deps.save_news(deps.news_store)
        return {"success": True, "action": action, "total_news": len(deps.news_store), "results": results}

    elif action == "refresh_source":
        source = req.source
        if not source:
            return {"success": False, "action": action, "error": "source is required"}
        if source in deps.NEWSNOW_CRAWLERS:
            crawler = deps.NEWSNOW_CRAWLERS[source]
            items = await crawler.crawl()
        elif any(feed.id == source for feed in deps.DEFAULT_RSS_FEEDS):
            feed = next(f for f in deps.DEFAULT_RSS_FEEDS if f.id == source)
            from crawlers.rss import RSSCrawler
            crawler = RSSCrawler(feed)
            items = await crawler.crawl()
        else:
            return {"success": False, "action": action, "error": f"Unknown source: {source}"}
        async with deps.news_lock:
            filtered = deps.kw_filter.filter_newsitems(items)
            new_count = 0
            for item in filtered:
                item_dict = item.to_dict()
                if not any(n["news_id"] == item_dict["news_id"] for n in deps.news_store):
                    deps.news_store.append(item_dict)
                    new_count += 1
            await deps.save_news(deps.news_store)
        return {"success": True, "action": action, "source": source, "total": len(items), "new": new_count}

    else:
        return {"success": False, "action": action, "error": f"Unknown action: {action}"}
