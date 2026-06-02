"""Agent smart API routes: chat with function calling, execute, trends, compare, search, briefing."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import NEWS_SOURCES
from . import deps
from core.interpreter import NewsInterpreter
from core.style_manager import StyleType, prompt_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])


# ── System Prompt ──────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """\
你是一位资深金融财经分析师，同时精通自媒体内容创作。你集成在新闻网站内，拥有多种工具可以调用，帮助用户获取信息、深度解读新闻、生成多平台内容。

## 核心视角

一切新闻解读以金融、财经、经济、政策为第一视角：
- **宏观层面**：关注货币政策、财政政策、产业政策、监管动向对市场的影响
- **行业层面**：分析产业链上下游联动、竞争格局变化、技术替代趋势
- **市场层面**：研判对资本市场（A股/港股/美股）、大宗商品、汇率的影响
- **微观层面**：评估对企业盈利、估值、商业模式的结构性影响
- **个人层面**：提炼对普通投资者、消费者、从业者的实际意义

分析时须区分「事实」与「判断」——事实必须严格依据原文，判断须标注置信度。

## 你的能力

1. **自由聊天** — 回答用户的任何问题，尤其是金融、财经、经济、政策领域
2. **新闻解读** — 使用 get_news_content 工具获取新闻内容后进行深度分析
3. **热点趋势** — 使用 get_trends 工具获取当前热门话题
4. **搜索新闻** — 使用 search_news 工具搜索特定话题
5. **多源对比** — 使用 compare_sources 工具获取不同来源的报道后进行对比分析
6. **每日简报** — 使用 get_briefing_data 工具获取新闻数据后生成简报
7. **执行操作** — 使用 refresh_news / refresh_source 工具刷新新闻数据
8. **知识库检索** — 使用 search_knowledge_base 工具搜索用户上传的知识库文档，获取相关文档片段作为参考

## 生成文章的风格指南

当用户要求生成文章时，请先使用 get_news_content 获取新闻内容，然后按照指定风格生成。切换风格时，你的专业人设也相应切换：

### 小红书风格
**人设**：拥有50万粉丝的财经类小红书博主，擅长把复杂的金融政策讲成"大白话"，让理财小白也能秒懂。

- 标题用 emoji 开头，制造信息差感（"💰这条消息90%的人还不知道"）
- 短段落，口语化，像闺蜜聊天一样讲财经
- 关键数字用类比解释（"相当于每个人多花了X元"）
- 多用 emoji 但不过度，emoji 仅作视觉引导不替代内容
- 结尾给行动建议 + 互动引导（"你们怎么看？评论区聊聊👇"）
- 末尾附 3-5 个话题标签（#财经 #理财 等）
- 严格控制在 800 字以内

### 微信公众号风格
**人设**：头部财经公众号主笔，曾任券商研究所分析师，行文严谨但不枯燥，善于从数据中挖掘被忽略的逻辑。

- 标题简洁有力，点明核心结论或悬念，不做标题党
- **开头**（150字内）：用新闻中最有冲击力的数据或事实切入
- **核心分析**：分 2-4 节，每节含关键事实 + 逻辑推演 + 数据支撑
- **影响研判**：从宏观和微观两个层面分析深远影响
- **结尾**：前瞻性判断，语言克制但有洞见
- 引用数据标注来源语境（"据原文披露"），不编造数据
- 篇幅 1200-1800 字

### 抖音风格
**人设**：百万粉丝财经抖音博主，以"3分钟看懂X"系列闻名，擅长用最短时间把财经新闻讲透。

- 极简标题，数字冲击力强（"3分钟看懂！央行降息意味着什么"）
- 短平快，每句不超过 20 字，适合口播
- 开头 3 秒钩子：最反直觉或最震撼的一句
- 正文 3 个要点，用"第一！""第二！""第三！"引导节奏
- 数字口语化（"涨了六成"而非"增长了60%"）
- 结尾互动引导（"你怎么看？评论区告诉我！"）
- 总时长 60 秒口播以内，约 200-300 字

可用新闻源：""" + "\n".join(f"- {k}: {v}" for k, v in NEWS_SOURCES.items()) + """

## 规则

- 当用户的问题可以通过工具获取数据时，优先使用工具
- 工具返回的数据是原始信息，请用专业视角整理后回复用户
- 解读新闻时，先调用 get_news_content 获取完整内容，再进行深度分析
- 分析必须基于新闻事实，不得编造原文未提及的数据或结论
- 信息不足时明确标注"根据目前信息尚无法确认"，而非猜测
- 生成简报时，先调用 get_briefing_data 获取数据，再生成结构化简报
- 回复使用中文
"""


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
        from routers.knowledge import kb_search_internal
        return await kb_search_internal(query, top_k)

    return [refresh_news, refresh_source, get_trends, search_news, compare_sources, get_news_content, get_briefing_data, search_knowledge_base]


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


@router.post("/chat/stream")
async def agent_chat_stream(req: AgentChatRequest):
    """Agent chat with function calling. LLM can invoke tools to fetch data and execute actions."""
    tools = _create_tools(req.current_news_id, req.news_ids)
    tool_map = {t.name: t for t in tools}

    # Use deepseek-chat alias to avoid thinking mode issues with reasoning_content
    from langchain_openai import ChatOpenAI
    from config import LLM_API_KEY, LLM_BASE_URL
    agent_llm = ChatOpenAI(
        model="deepseek-chat",
        temperature=0.7,
        openai_api_key=LLM_API_KEY,
        openai_api_base=LLM_BASE_URL,
        request_timeout=120,
        max_retries=2,
    )

    current_news_text = ""
    if req.current_news_id:
        current_item = deps.find_news(req.current_news_id)
        if current_item:
            await deps.ensure_content(current_item)
            current_news_text = f"\n\n当前用户正在查看的新闻：{current_item.get('title', '')}"

    human = req.message
    if req.news_ids:
        human = f"用户选中的新闻ID: {', '.join(req.news_ids)}\n\n{req.message}"

    async def event_stream():
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
        from langchain_core.utils.function_calling import convert_to_openai_tool

        prompt_text = f"[System]\n{AGENT_SYSTEM_PROMPT + current_news_text}\n\n[User]\n{human}"
        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"

        messages = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT + current_news_text),
            HumanMessage(content=human),
        ]
        openai_tools = [convert_to_openai_tool(t) for t in tools]
        llm_with_tools = agent_llm.bind(tools=openai_tools)

        for _ in range(5):
            response = await llm_with_tools.ainvoke(messages)

            tool_calls = getattr(response, 'tool_calls', None) or response.additional_kwargs.get('tool_calls', None)
            if not tool_calls:
                # Pure text — stream it by re-invoking with astream
                messages.append(response)
                async for chunk in llm_with_tools.astream(messages[:-1]):
                    if chunk.content:
                        data = json.dumps({"type": "chunk", "content": chunk.content}, ensure_ascii=False)
                        yield f"data: {data}\n\n"
                break

            # Tool calls detected — execute them
            # If the response had text before tool calls, stream it
            if response.content:
                data = json.dumps({"type": "chunk", "content": response.content}, ensure_ascii=False)
                yield f"data: {data}\n\n"

            # Inject reasoning_content into additional_kwargs if present in raw response
            # (DeepSeek V4 thinking mode requires it for subsequent calls)
            rc = getattr(response, "reasoning_content", None)
            if rc:
                response.additional_kwargs["reasoning_content"] = rc

            messages.append(response)

            for tc in tool_calls:
                if hasattr(tc, 'name') and hasattr(tc, 'args') and hasattr(tc, 'id'):
                    tc_name = tc.name
                    tc_args = tc.args
                    tc_id = tc.id
                elif isinstance(tc, dict):
                    func = tc.get('function', {})
                    tc_name = func.get('name', tc.get('name', ''))
                    tc_args_raw = func.get('arguments', tc.get('args', '{}'))
                    tc_args = json.loads(tc_args_raw) if isinstance(tc_args_raw, str) else tc_args_raw
                    tc_id = tc.get('id', '')
                else:
                    tc_name = ''
                    tc_args = {}
                    tc_id = ''

                if not tc_name:
                    logger.warning("Tool call with empty name, id=%s", tc_id)
                    messages.append(ToolMessage(content="Error: tool call with empty name", tool_call_id=tc_id or "unknown"))
                    continue
                
                display_name = TOOL_DISPLAY_NAMES.get(tc_name, tc_name)
                yield f"data: {json.dumps({'type': 'loading', 'message': f'正在{display_name}...'}, ensure_ascii=False)}\n\n"

                try:
                    if tc_name not in tool_map:
                        result = f"未知工具：{tc_name}"
                    else:
                        result = await tool_map[tc_name].ainvoke(tc_args)
                except Exception as e:
                    logger.exception("Tool %s failed", tc_name)
                    result = f"工具执行失败：{e}"

                messages.append(ToolMessage(content=str(result), tool_call_id=tc_id))

                # Tools with frontend side effects
                if tc_name in ("refresh_news", "refresh_source"):
                    yield f"data: {json.dumps({'type': 'action', 'action': {'action': tc_name, **tc_args}}, ensure_ascii=False)}\n\n"

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
