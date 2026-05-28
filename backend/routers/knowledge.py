"""Knowledge base API routes: KB CRUD, upload, list, delete, search, RAG chat, RAG generate, conversations."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import UPLOAD_DIR, LLM_API_KEY, LLM_BASE_URL
from database import (
    create_kb,
    load_kbs,
    load_kb,
    delete_kb as db_delete_kb,
    save_kb_doc,
    load_kb_docs,
    delete_kb_doc,
    save_kb_chunks,
    load_kb_chunk_texts,
    create_conversation,
    load_conversations,
    delete_conversation,
    save_message,
    load_messages,
)
from knowledge.embeddings import DashScopeEmbedding
from knowledge.chunker import TextChunker
from knowledge.vectorstore import VectorStoreManager
from knowledge.loader import DocumentLoader

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

embedding_client = DashScopeEmbedding()
chunker = TextChunker()
loader = DocumentLoader()
vs_manager = VectorStoreManager()


KB_RAG_SYSTEM_PROMPT = """\
你是知识库AI助手。以下是从知识库中检索到的相关文档片段，请基于这些内容回答用户问题。

规则：
- 严格基于知识库内容回答，不得编造知识库中未提及的信息
- 引用知识库内容时，标注来源文件名
- 如果知识库中没有相关信息，请明确说明"知识库中暂无相关信息"
- 回复使用中文
"""

KB_GENERATE_SYSTEM_PROMPT = """\
你是资深财经内容创作者。以下是从知识库中检索到的相关内容，请基于这些内容生成文章。

规则：
- 严格基于知识库内容，不得编造数据
- 引用数据标注来源文件
- 回复使用中文
"""


# ── KB CRUD ────────────────────────────────────────────────────

class CreateKBRequest(BaseModel):
    name: str
    description: str = ""


@router.post("/bases")
async def create_knowledge_base(req: CreateKBRequest):
    kb_id = uuid.uuid4().hex[:12]
    kb_dir = Path(UPLOAD_DIR) / kb_id
    kb_dir.mkdir(parents=True, exist_ok=True)
    await create_kb({"kb_id": kb_id, "name": req.name, "description": req.description})
    return {"kb_id": kb_id, "name": req.name, "description": req.description}


@router.get("/bases")
async def list_knowledge_bases():
    kbs = await load_kbs()
    result = []
    for kb in kbs:
        docs = await load_kb_docs(kb["kb_id"])
        total_chunks = sum(d.get("chunk_count", 0) for d in docs)
        result.append({**kb, "doc_count": len(docs), "total_chunks": total_chunks})
    return {"knowledge_bases": result}


@router.get("/bases/{kb_id}")
async def get_knowledge_base(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    docs = await load_kb_docs(kb_id)
    total_chunks = sum(d.get("chunk_count", 0) for d in docs)
    convs = await load_conversations(kb_id)
    return {**kb, "doc_count": len(docs), "total_chunks": total_chunks, "conversation_count": len(convs)}


@router.delete("/bases/{kb_id}")
async def delete_knowledge_base(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    chunk_ids = await db_delete_kb(kb_id)
    vs_manager.remove(kb_id)

    kb_dir = Path(UPLOAD_DIR) / kb_id
    if kb_dir.exists():
        for f in kb_dir.iterdir():
            f.unlink(missing_ok=True)
        try:
            kb_dir.rmdir()
        except Exception:
            pass

    return {"deleted": True, "kb_id": kb_id}


# ── Upload ──────────────────────────────────────────────────────

@router.post("/bases/{kb_id}/upload")
async def upload_document(kb_id: str, file: UploadFile = File(...)):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    if not file.filename:
        raise HTTPException(400, "No filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in loader.SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}. Supported: {loader.SUPPORTED_EXTENSIONS}")

    upload_dir = Path(UPLOAD_DIR) / kb_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    doc_id = uuid.uuid4().hex[:16]
    save_path = upload_dir / f"{doc_id}{ext}"

    content = await file.read()
    save_path.write_bytes(content)

    try:
        doc = loader.load(save_path, doc_id=doc_id)
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Failed to parse document: {e}")

    if not doc.text.strip():
        save_path.unlink(missing_ok=True)
        raise HTTPException(400, "Document has no extractable text")

    chunks = chunker.chunk_with_pages(doc.pages, doc_id=doc_id)
    if not chunks:
        save_path.unlink(missing_ok=True)
        raise HTTPException(400, "Document too short to chunk")

    try:
        texts = [c.text for c in chunks]
        vectors = embedding_client.embed(texts)
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Embedding failed: {e}")

    chunk_ids = [c.chunk_id for c in chunks]
    vector_store = vs_manager.get(kb_id)
    vector_store.add(chunk_ids, vectors)

    chunk_dicts = [
        {
            "chunk_id": c.chunk_id,
            "doc_id": doc_id,
            "chunk_index": c.chunk_index,
            "page": c.page,
            "text": c.text,
        }
        for c in chunks
    ]
    await save_kb_chunks(chunk_dicts)

    doc_record = {
        "doc_id": doc_id,
        "kb_id": kb_id,
        "filename": file.filename,
        "file_type": ext,
        "chunk_count": len(chunks),
        "file_size": len(content),
        "upload_time": "",
        "status": "ready",
    }
    await save_kb_doc(doc_record)

    return {
        "doc_id": doc_id,
        "filename": file.filename,
        "chunk_count": len(chunks),
        "file_size": len(content),
    }


# ── List ────────────────────────────────────────────────────────

@router.get("/bases/{kb_id}/documents")
async def list_documents(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    docs = await load_kb_docs(kb_id)
    total_chunks = sum(d.get("chunk_count", 0) for d in docs)
    return {"documents": docs, "total_chunks": total_chunks}


# ── Delete ──────────────────────────────────────────────────────

@router.delete("/bases/{kb_id}/documents/{doc_id}")
async def delete_document(kb_id: str, doc_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    deleted_chunk_ids = await delete_kb_doc(doc_id)
    if deleted_chunk_ids:
        vector_store = vs_manager.get(kb_id)
        vector_store.remove_by_doc(set(deleted_chunk_ids))

    upload_dir = Path(UPLOAD_DIR) / kb_id
    for ext in loader.SUPPORTED_EXTENSIONS:
        p = upload_dir / f"{doc_id}{ext}"
        if p.exists():
            p.unlink()

    return {"deleted": True, "doc_id": doc_id, "chunks_removed": len(deleted_chunk_ids)}


# ── Search ──────────────────────────────────────────────────────

class KBSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/bases/{kb_id}/search")
async def search_knowledge(kb_id: str, req: KBSearchRequest):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        return {"results": [], "total": 0}

    try:
        query_vec = embedding_client.embed_query(req.query)
    except Exception as e:
        raise HTTPException(500, f"Embedding query failed: {e}")

    hits = vector_store.search(query_vec, top_k=req.top_k)
    if not hits:
        return {"results": [], "total": 0}

    chunk_ids = [cid for cid, _ in hits]
    score_map = {cid: score for cid, score in hits}
    chunk_data = await load_kb_chunk_texts(chunk_ids)

    results = []
    for cid in chunk_ids:
        if cid in chunk_data:
            cd = chunk_data[cid]
            preview = cd["text"][:120] + ("..." if len(cd["text"]) > 120 else "")
            results.append({
                "chunk_id": cid,
                "doc_id": cd["doc_id"],
                "filename": cd["filename"],
                "page": cd["page"],
                "text": cd["text"],
                "preview": preview,
                "score": round(score_map.get(cid, 0), 4),
            })

    return {"results": results, "total": len(results)}


# ── Conversations ──────────────────────────────────────────────

class CreateConvRequest(BaseModel):
    title: str = ""


@router.post("/bases/{kb_id}/conversations")
async def create_conv(kb_id: str, req: CreateConvRequest):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    conv_id = uuid.uuid4().hex[:12]
    await create_conversation({"conv_id": conv_id, "kb_id": kb_id, "title": req.title})
    return {"conv_id": conv_id, "kb_id": kb_id, "title": req.title}


@router.get("/bases/{kb_id}/conversations")
async def list_conversations(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    convs = await load_conversations(kb_id)
    return {"conversations": convs}


@router.delete("/bases/{kb_id}/conversations/{conv_id}")
async def delete_conv(kb_id: str, conv_id: str):
    await delete_conversation(conv_id)
    return {"deleted": True, "conv_id": conv_id}


@router.get("/bases/{kb_id}/conversations/{conv_id}/messages")
async def get_messages(kb_id: str, conv_id: str):
    msgs = await load_messages(conv_id)
    for m in msgs:
        if m.get("sources"):
            try:
                m["sources"] = json.loads(m["sources"])
            except Exception:
                m["sources"] = []
        else:
            m["sources"] = []
    return {"messages": msgs}


class SaveMessageRequest(BaseModel):
    role: str
    content: str
    type: str = "chat"
    sources: list = Field(default_factory=list)


@router.post("/bases/{kb_id}/conversations/{conv_id}/messages")
async def save_msg(kb_id: str, conv_id: str, req: SaveMessageRequest):
    msg_id = uuid.uuid4().hex[:12]
    await save_message({
        "msg_id": msg_id,
        "conv_id": conv_id,
        "role": req.role,
        "content": req.content,
        "type": req.type,
        "sources": json.dumps(req.sources, ensure_ascii=False) if req.sources else "",
    })
    return {"msg_id": msg_id}


# ── RAG Chat (SSE stream) ──────────────────────────────────────

class KBChatRequest(BaseModel):
    message: str
    doc_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=10)
    conv_id: str = ""


@router.post("/bases/{kb_id}/chat/stream")
async def kb_chat_stream(kb_id: str, req: KBChatRequest):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        raise HTTPException(400, "Knowledge base is empty. Please upload documents first.")

    try:
        query_vec = embedding_client.embed_query(req.message)
    except Exception as e:
        raise HTTPException(500, f"Embedding failed: {e}")

    hits = vector_store.search(query_vec, top_k=req.top_k)
    chunk_ids = [cid for cid, _ in hits]
    chunk_data = await load_kb_chunk_texts(chunk_ids)

    context_parts = []
    for cid in chunk_ids:
        if cid in chunk_data:
            cd = chunk_data[cid]
            page_info = f", 第{cd['page']}页" if cd.get("page", 0) > 0 else ""
            context_parts.append(f"[来源: {cd['filename']}{page_info}]\n{cd['text']}")

    context_text = "\n\n".join(context_parts) if context_parts else "（未检索到相关内容）"

    full_system = KB_RAG_SYSTEM_PROMPT + f"\n\n【知识库内容】\n{context_text}"

    async def event_stream():
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatOpenAI(
            model="deepseek-chat",
            temperature=0.7,
            openai_api_key=LLM_API_KEY,
            openai_api_base=LLM_BASE_URL,
            request_timeout=120,
            max_retries=2,
        )

        prompt_text = f"[System]\n{full_system}\n\n[User]\n{req.message}"
        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"

        sources = [{"filename": chunk_data[cid]["filename"], "page": chunk_data[cid].get("page", 0), "score": round(score, 4), "text": chunk_data[cid]["text"], "preview": chunk_data[cid]["text"][:80] + ("..." if len(chunk_data[cid]["text"]) > 80 else "")}
                   for cid, score in hits if cid in chunk_data]
        if sources:
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"

        messages = [
            SystemMessage(content=full_system),
            HumanMessage(content=req.message),
        ]

        full_content = ""
        try:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_content += chunk.content
                    data = json.dumps({"type": "chunk", "content": chunk.content}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        if req.conv_id and full_content:
            msg_id = uuid.uuid4().hex[:12]
            await save_message({
                "msg_id": msg_id,
                "conv_id": req.conv_id,
                "role": "assistant",
                "content": full_content,
                "type": "chat",
                "sources": json.dumps(sources, ensure_ascii=False) if sources else "",
            })

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ── RAG Generate Article (SSE stream) ──────────────────────────

class KBGenerateRequest(BaseModel):
    message: str = ""
    style: str = "wechat_mp"
    doc_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=10)
    conv_id: str = ""


@router.post("/bases/{kb_id}/generate/stream")
async def kb_generate_stream(kb_id: str, req: KBGenerateRequest):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        raise HTTPException(400, "Knowledge base is empty. Please upload documents first.")

    query = req.message or "总结知识库核心内容"
    try:
        query_vec = embedding_client.embed_query(query)
    except Exception as e:
        raise HTTPException(500, f"Embedding failed: {e}")

    hits = vector_store.search(query_vec, top_k=req.top_k)
    chunk_ids = [cid for cid, _ in hits]
    chunk_data = await load_kb_chunk_texts(chunk_ids)

    context_parts = []
    for cid in chunk_ids:
        if cid in chunk_data:
            cd = chunk_data[cid]
            page_info = f", 第{cd['page']}页" if cd.get("page", 0) > 0 else ""
            context_parts.append(f"[来源: {cd['filename']}{page_info}]\n{cd['text']}")

    context_text = "\n\n".join(context_parts) if context_parts else "（未检索到相关内容）"

    style_labels = {"xiaohongshu": "小红书", "wechat_mp": "微信公众号", "douyin": "抖音"}
    style_label = style_labels.get(req.style, req.style)

    full_system = KB_GENERATE_SYSTEM_PROMPT + f"\n\n【知识库内容】\n{context_text}"

    style_hints = {
        "xiaohongshu": "请用小红书风格生成：emoji开头标题、短段落口语化、关键数字用类比、结尾互动引导+话题标签、800字以内",
        "wechat_mp": "请用公众号风格生成：简洁有力标题、开头用数据切入、分2-4节含事实+逻辑+数据、影响研判、前瞻判断、1200-1800字",
        "douyin": "请用抖音风格生成：极简数字标题、短平快每句不超20字、3个要点节奏感、数字口语化、200-300字",
    }
    human = req.message or f"请基于知识库内容生成一篇{style_label}风格的文章"
    if req.style in style_hints:
        human += f"\n\n{style_hints[req.style]}"

    async def event_stream():
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatOpenAI(
            model="deepseek-chat",
            temperature=0.7,
            openai_api_key=LLM_API_KEY,
            openai_api_base=LLM_BASE_URL,
            request_timeout=120,
            max_retries=2,
        )

        prompt_text = f"[System]\n{full_system}\n\n[User]\n{human}"
        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"

        sources = [{"filename": chunk_data[cid]["filename"], "page": chunk_data[cid].get("page", 0), "score": round(score, 4), "text": chunk_data[cid]["text"], "preview": chunk_data[cid]["text"][:80] + ("..." if len(chunk_data[cid]["text"]) > 80 else "")}
                   for cid, score in hits if cid in chunk_data]
        if sources:
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"

        messages = [
            SystemMessage(content=full_system),
            HumanMessage(content=human),
        ]

        full_content = ""
        try:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_content += chunk.content
                    data = json.dumps({"type": "chunk", "content": chunk.content}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        if req.conv_id and full_content:
            msg_id = uuid.uuid4().hex[:12]
            await save_message({
                "msg_id": msg_id,
                "conv_id": req.conv_id,
                "role": "assistant",
                "content": full_content,
                "type": "article",
                "sources": json.dumps(sources, ensure_ascii=False) if sources else "",
            })

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ── Internal search (for agent tool) ──────────────────────────

async def kb_search_internal(query: str, top_k: int = 5) -> str:
    kbs = await load_kbs()
    if not kbs:
        return "知识库为空，暂无可用文档。"

    all_results = []
    for kb in kbs:
        vector_store = vs_manager.get(kb["kb_id"])
        if vector_store.total_vectors == 0:
            continue
        try:
            query_vec = embedding_client.embed_query(query)
        except Exception:
            continue
        hits = vector_store.search(query_vec, top_k=top_k)
        if not hits:
            continue
        chunk_ids = [cid for cid, _ in hits]
        chunk_data = await load_kb_chunk_texts(chunk_ids)
        for cid, score in hits:
            if cid in chunk_data:
                cd = chunk_data[cid]
                page_info = f", 第{cd['page']}页" if cd.get("page", 0) > 0 else ""
                all_results.append(f"[知识库: {kb['name']}, 来源: {cd['filename']}{page_info}, 相关度: {score:.2f}]\n{cd['text']}")

    if not all_results:
        return "未在知识库中找到与查询相关的内容。"

    return "\n\n".join(all_results)
