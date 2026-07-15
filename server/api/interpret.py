"""AI interpretation and article generation API routes."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from database import save_article

from . import deps

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["interpret"])


class InterpretRequest(BaseModel):
    news_id: str
    style: str = "wechat_mp"


class ChatRequest(BaseModel):
    message: str
    news_ids: list[str] = Field(default_factory=list)


class GenerateArticleRequest(BaseModel):
    news_ids: list[str] = Field(..., min_length=1)
    style: str = "wechat_mp"
    title: str | None = None
    prompt: str | None = None


LIMITED_CONTENT_MSG = (
    "该新闻原文为动态加载内容，无法自动获取正文。请在详情中点击「新窗口打开」查看原文，获取足够信息后再进行解读。"
)


def _check_limited_items(items: list[dict]) -> list[str]:
    """Return titles of items with limited content."""
    return [item.get("title", "") for item in items if deps.is_limited_content(item)]


@router.post("/interpret")
async def interpret_news(req: InterpretRequest):
    item = await deps.find_news(req.news_id)
    if not item:
        raise HTTPException(404, f"News not found: {req.news_id}")

    await deps.ensure_content(item)
    if deps.is_limited_content(item):
        return {"news_id": req.news_id, "style": req.style, "interpretation": LIMITED_CONTENT_MSG}

    style = deps.resolve_style(req.style)
    result = await deps.interpreter.interpret([item], style)
    return {"news_id": req.news_id, "style": req.style, "interpretation": result}


@router.post("/chat")
async def chat_interpret(req: ChatRequest):
    items = await deps.find_news_batch(req.news_ids)
    for item in items:
        await deps.ensure_content(item)

    limited = _check_limited_items(items)
    if limited and not any(not deps.is_limited_content(i) for i in items):
        return {"response": LIMITED_CONTENT_MSG}

    result = await deps.interpreter.chat(req.message, items)
    return {"response": result}


@router.post("/generate_article")
async def generate_article(req: GenerateArticleRequest):
    items = await deps.find_news_batch(req.news_ids)
    if not items:
        raise HTTPException(400, "No valid news items found for given IDs")

    for item in items:
        await deps.ensure_content(item)

    limited = _check_limited_items(items)
    if limited and not any(not deps.is_limited_content(i) for i in items):
        raise HTTPException(400, LIMITED_CONTENT_MSG)

    style = deps.resolve_style(req.style)
    article = await deps.interpreter.generate_article(items, style, req.title, prompt=req.prompt)
    article["article_id"] = f"art_{uuid4().hex[:12]}"

    async with deps.article_lock:
        # 先落库（DB 事实来源），再回填缓存（append 即同步缓存）。
        await save_article(article)
        deps.article_store.append(article)

    return article


@router.post("/interpret/stream")
async def interpret_news_stream(req: InterpretRequest):
    item = await deps.find_news(req.news_id)
    if not item:
        raise HTTPException(404, f"News not found: {req.news_id}")

    style = deps.resolve_style(req.style)

    async def event_stream():
        yield f"data: {json.dumps({'type': 'loading', 'message': '正在获取原文内容...'}, ensure_ascii=False)}\n\n"
        await deps.ensure_content(item)

        if deps.is_limited_content(item):
            yield f"data: {json.dumps({'type': 'limited', 'message': LIMITED_CONTENT_MSG}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        prompt_text = deps.interpreter.build_prompt_text([item], style, task="interpret")
        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"

        async for chunk in deps.interpreter.astream_interpret([item], style, task="interpret"):
            data = json.dumps({"type": "chunk", "content": chunk}, ensure_ascii=False)
            yield f"data: {data}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=deps.SSE_HEADERS)


@router.post("/chat/stream")
async def chat_interpret_stream(req: ChatRequest):
    items = await deps.find_news_batch(req.news_ids)

    async def event_stream():
        if items:
            yield f"data: {json.dumps({'type': 'loading', 'message': '正在获取原文内容...'}, ensure_ascii=False)}\n\n"
            for item in items:
                await deps.ensure_content(item)

        limited = _check_limited_items(items) if items else []
        if limited and not any(not deps.is_limited_content(i) for i in items):
            yield f"data: {json.dumps({'type': 'limited', 'message': LIMITED_CONTENT_MSG}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        prompt_text = deps.interpreter.build_prompt_text(items, message=req.message, task="chat")
        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"

        async for chunk in deps.interpreter.astream_chat(req.message, items):
            data = json.dumps({"type": "chunk", "content": chunk}, ensure_ascii=False)
            yield f"data: {data}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=deps.SSE_HEADERS)


@router.post("/generate_article/stream")
async def generate_article_stream(req: GenerateArticleRequest):
    items = await deps.find_news_batch(req.news_ids)
    if not items:
        raise HTTPException(400, "No valid news items found for given IDs")

    style = deps.resolve_style(req.style)

    if not req.title:
        if style == deps.StyleType.XIAOHONGSHU:
            req.title = f"🌟 {' & '.join(n.get('title', '')[:20] for n in items[:2])} 深度解读"
        elif style == deps.StyleType.DOUYIN:
            req.title = f"🔥 {' '.join(n.get('title', '')[:15] for n in items[:2])}"
        else:
            req.title = f"深度解读 | {' · '.join(n.get('title', '')[:15] for n in items[:2])}"

    article_id = f"art_{uuid4().hex[:12]}"

    async def event_stream():
        meta = json.dumps(
            {
                "type": "meta",
                "article_id": article_id,
                "title": req.title,
                "style": style.value,
                "news_ids": [n.get("news_id") for n in items],
            },
            ensure_ascii=False,
        )
        yield f"data: {meta}\n\n"

        yield f"data: {json.dumps({'type': 'loading', 'message': '正在获取原文内容...'}, ensure_ascii=False)}\n\n"
        for item in items:
            await deps.ensure_content(item)

        limited = _check_limited_items(items)
        if limited and not any(not deps.is_limited_content(i) for i in items):
            yield f"data: {json.dumps({'type': 'limited', 'message': LIMITED_CONTENT_MSG}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        prompt_text = deps.interpreter.build_prompt_text(items, style, prompt=req.prompt, task="generate")
        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"

        full_content = ""
        async for chunk in deps.interpreter.astream_interpret(items, style, prompt=req.prompt, task="generate"):
            full_content += chunk
            data = json.dumps({"type": "chunk", "content": chunk}, ensure_ascii=False)
            yield f"data: {data}\n\n"

        article = {
            "article_id": article_id,
            "title": req.title,
            "content": full_content,
            "style": style.value,
            "news_ids": [n.get("news_id") for n in items],
        }
        async with deps.article_lock:
            # 先落库（DB 事实来源），再回填缓存（append 即同步缓存）。
            await save_article(article)
            deps.article_store.append(article)

        done = json.dumps({"type": "done", "article_id": article_id}, ensure_ascii=False)
        yield f"data: {done}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=deps.SSE_HEADERS)
