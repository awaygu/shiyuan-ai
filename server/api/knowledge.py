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

from config import (
    UPLOAD_DIR, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, KB_EMBEDDING_DIM, MAX_UPLOAD_SIZE,
    TEMPERATURE_GENERATE,
    MAX_RAG_CONTEXT_CHARS,
)
from core.style_manager import prompt_manager
from database import (
    create_kb,
    load_kbs,
    load_kb,
    update_kb as db_update_kb,
    delete_kb as db_delete_kb,
    save_kb_doc,
    load_kb_docs,
    delete_kb_doc,
    rename_kb_doc,
    save_kb_chunks,
    load_kb_chunk_texts,
    create_conversation,
    load_conversations,
    delete_conversation,
    save_message,
    load_messages,
    clear_kb_messages,
)
from rag.embeddings import DashScopeEmbedding
from rag.chunker import TextChunker
from rag.vectorstore import VectorStoreManager
from rag.loader import DocumentLoader, IMAGE_EXTENSIONS

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
vs_manager = VectorStoreManager(dim=KB_EMBEDDING_DIM)


vs_manager = VectorStoreManager(dim=KB_EMBEDDING_DIM)

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


class UpdateKBRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.patch("/bases/{kb_id}")
async def update_knowledge_base(kb_id: str, req: UpdateKBRequest):
    if req.name is None and req.description is None:
        raise HTTPException(400, "At least one of name or description must be provided")
    kb = await db_update_kb(kb_id, name=req.name, description=req.description)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    return kb


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

async def _process_single_upload(kb_id: str, file: UploadFile) -> dict:
    if not file.filename:
        raise HTTPException(400, "No filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in loader.SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}. Supported: {loader.SUPPORTED_EXTENSIONS}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large: {len(content)} bytes (max {MAX_UPLOAD_SIZE} bytes)")

    upload_dir = Path(UPLOAD_DIR) / kb_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    doc_id = uuid.uuid4().hex[:16]
    save_path = upload_dir / f"{doc_id}{ext}"

    save_path.write_bytes(content)

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        doc = await loop.run_in_executor(None, loader.load, save_path, doc_id)
    except Exception as e:
        logger.error("Document parse failed: %s", e, exc_info=True)
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Failed to parse document: {e}")

    if not doc.text.strip():
        save_path.unlink(missing_ok=True)
        raise HTTPException(400, "Document has no extractable text")

    from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
    from openai import OpenAI as LLMClient

    doc_summary = ""
    try:
        llm_client = LLMClient(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=30.0, max_retries=2)
        summary_text = doc.text[:3000]
        summary_completion = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt_manager.doc_summary_system_prompt},
                {"role": "user", "content": summary_text},
            ],
        )
        doc_summary = (summary_completion.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("Summary generation failed for %s: %s", doc_id, e)

    chunks = chunker.chunk_with_pages(doc.pages, doc_id=doc_id)
    if not chunks:
        save_path.unlink(missing_ok=True)
        raise HTTPException(400, "Document too short to chunk")

    try:
        texts = [c.text for c in chunks]
        vectors = await embedding_client.embed_async(texts)
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Embedding failed: {e}")

    chunk_ids = [c.chunk_id for c in chunks]
    await vs_manager.add_async(kb_id, chunk_ids, vectors, doc_id)

    doc_record = {
        "doc_id": doc_id,
        "kb_id": kb_id,
        "filename": f"{doc.generated_name}{ext}" if doc.generated_name else file.filename,
        "file_type": ext,
        "chunk_count": len(chunks),
        "file_size": len(content),
        "upload_time": "",
        "status": "ready",
        "summary": doc_summary,
    }
    await save_kb_doc(doc_record)

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

    final_filename = doc_record["filename"]
    return {
        "doc_id": doc_id,
        "filename": final_filename,
        "chunk_count": len(chunks),
        "file_size": len(content),
    }


@router.post("/bases/{kb_id}/upload")
async def upload_documents(kb_id: str, files: list[UploadFile] = File(...)):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    results = []
    errors = []
    for file in files:
        try:
            result = await _process_single_upload(kb_id, file)
            results.append(result)
        except HTTPException as e:
            errors.append({"filename": file.filename, "detail": e.detail})
        except Exception as e:
            errors.append({"filename": file.filename, "detail": str(e)})

    return {"results": results, "errors": errors}


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

@router.get("/bases/{kb_id}/documents/{doc_id}")
async def get_document(kb_id: str, doc_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    docs = await load_kb_docs(kb_id)
    for d in docs:
        if d["doc_id"] == doc_id:
            return d
    raise HTTPException(404, "Document not found")


class RenameDocRequest(BaseModel):
    filename: str


@router.patch("/bases/{kb_id}/documents/{doc_id}")
async def rename_document(kb_id: str, doc_id: str, req: RenameDocRequest):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    if not req.filename.strip():
        raise HTTPException(400, "Filename cannot be empty")
    ok = await rename_kb_doc(doc_id, req.filename.strip())
    if not ok:
        raise HTTPException(404, "Document not found")
    return {"doc_id": doc_id, "filename": req.filename.strip()}


@router.delete("/bases/{kb_id}/documents/{doc_id}")
async def delete_document(kb_id: str, doc_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    deleted_chunk_ids = await delete_kb_doc(doc_id)
    if deleted_chunk_ids:
        await vs_manager.remove_by_doc_async(kb_id, set(deleted_chunk_ids))

    upload_dir = Path(UPLOAD_DIR) / kb_id
    for ext in loader.SUPPORTED_EXTENSIONS:
        p = upload_dir / f"{doc_id}{ext}"
        if p.exists():
            p.unlink()

    return {"deleted": True, "doc_id": doc_id, "chunks_removed": len(deleted_chunk_ids)}


# ── Search ──────────────────────────────────────────────────────

class KBSearchRequest(BaseModel):
    query: str
    doc_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=20)


@router.post("/bases/{kb_id}/search")
async def search_knowledge(kb_id: str, req: KBSearchRequest):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        return {"results": [], "total": 0}

    try:
        query_vec = await embedding_client.embed_query_async(req.query)
    except Exception as e:
        raise HTTPException(500, f"Embedding query failed: {e}")

    hits = vector_store.search(query_vec, top_k=req.top_k, doc_ids=req.doc_ids or None)
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


@router.get("/bases/{kb_id}/suggestions")
async def get_suggestions(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        return {"suggestions": []}

    docs = await load_kb_docs(kb_id)
    summaries = [d.get("summary", "") for d in docs if d.get("summary")]
    doc_names = [d["filename"] for d in docs]

    from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
    from openai import OpenAI as LLMClient

    try:
        llm_client = LLMClient(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=30.0, max_retries=2)
        context = ""
        if summaries:
            context = "文档概要：\n" + "\n".join(f"- {s}" for s in summaries[:5])
        else:
            context = "文档列表：" + "、".join(doc_names[:10])

        resp = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt_manager.question_generator_system_prompt},
                {"role": "user", "content": context},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        suggestions = [line.strip().lstrip("0123456789.-) ") for line in text.split("\n") if line.strip()]
        return {"suggestions": suggestions[:5]}
    except Exception as e:
        logger.warning("Suggestion generation failed for KB %s: %s", kb_id, e)
        return {"suggestions": []}


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


# ── RAG Chat (SSE stream, with short-term memory) ──────────────

class KBChatRequest(BaseModel):
    message: str
    doc_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=20)


def _kb_conv_id(kb_id: str) -> str:
    return f"kb_{kb_id}"


@router.post("/bases/{kb_id}/chat/stream")
async def kb_chat_stream(kb_id: str, req: KBChatRequest):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        raise HTTPException(400, "Knowledge base is empty. Please upload documents first.")

    conv_id = _kb_conv_id(kb_id)

    existing_convs = await load_conversations(kb_id)
    if not any(c["conv_id"] == conv_id for c in existing_convs):
        await create_conversation({"conv_id": conv_id, "kb_id": kb_id, "title": kb["name"]})

    from core.rag_graph import get_rag_graph, migrate_history
    from langchain_core.messages import HumanMessage, AIMessage

    rag_graph = await get_rag_graph()

    config = {"configurable": {"thread_id": conv_id}}

    existing_state = await rag_graph.aget_state(config)
    if not existing_state.values or not existing_state.values.get("messages"):
        old_messages = await migrate_history(conv_id)
        if old_messages:
            await rag_graph.aupdate_state(config, {"messages": old_messages}, as_node="generate")

    input_state = {
        "query": req.message,
        "kb_id": kb_id,
        "doc_ids": req.doc_ids,
        "top_k": req.top_k,
    }

    async def event_stream():
        prompt_sent = False
        sources_sent = False
        full_content = ""
        sources_out = []
        rewrite_info = None

        msg_id = uuid.uuid4().hex[:12]
        await save_message({
            "msg_id": msg_id,
            "conv_id": conv_id,
            "role": "user",
            "content": req.message,
            "type": "chat",
            "sources": "",
        })

        try:
            async for event in rag_graph.astream_events(
                input_state, config=config, version="v2"
            ):
                kind = event.get("event", "")

                if kind == "on_chain_end" and event.get("name") == "rewrite_query":
                    output = event.get("data", {}).get("output", {})
                    if output.get("rewritten_query") != req.message:
                        rewrite_info = {
                            "original": req.message,
                            "rewritten": output.get("rewritten_query", req.message),
                            "skip_retrieve": output.get("skip_retrieve", False),
                        }
                        yield f"data: {json.dumps({'type': 'rewrite', 'rewrite': rewrite_info}, ensure_ascii=False)}\n\n"

                elif kind == "on_chain_end" and event.get("name") == "retrieve":
                    output = event.get("data", {}).get("output", {})
                    sources_out = output.get("sources", [])
                    context_text = output.get("context", "")
                    prompt_text = f"[System]\n{prompt_manager.kb_rag_system_prompt}\n\n【知识库内容】\n{context_text}\n\n[User]\n{req.message}"
                    if not prompt_sent:
                        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"
                        prompt_sent = True
                    if sources_out and not sources_sent:
                        yield f"data: {json.dumps({'type': 'sources', 'sources': sources_out}, ensure_ascii=False)}\n\n"
                        sources_sent = True

                elif kind == "on_chat_model_stream":
                    if not prompt_sent:
                        cur_state = await rag_graph.aget_state(config)
                        last_sources = (cur_state.values or {}).get("last_sources", [])
                        last_context = (cur_state.values or {}).get("last_context", "")
                        prompt_text = f"[System]\n{prompt_manager.kb_rag_system_prompt}\n\n【知识库内容】\n{last_context}\n\n[User]\n{req.message}"
                        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"
                        prompt_sent = True
                        if last_sources and not sources_sent:
                            sources_out = last_sources
                            yield f"data: {json.dumps({'type': 'sources', 'sources': last_sources}, ensure_ascii=False)}\n\n"
                            sources_sent = True

                    chunk = event.get("data", {}).get("chunk")
                    if chunk and chunk.content:
                        full_content += chunk.content
                        data = json.dumps({"type": "chunk", "content": chunk.content}, ensure_ascii=False)
                        yield f"data: {data}\n\n"

            if not prompt_sent:
                yield f"data: {json.dumps({'type': 'prompt', 'content': f'[User]\\n{req.message}'}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        if full_content:
            asst_msg_id = uuid.uuid4().hex[:12]
            await save_message({
                "msg_id": asst_msg_id,
                "conv_id": conv_id,
                "role": "assistant",
                "content": full_content,
                "type": "chat",
                "sources": json.dumps(sources_out, ensure_ascii=False) if sources_out else "",
            })

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ── Clear KB Chat ───────────────────────────────────────────────

@router.delete("/bases/{kb_id}/chat/clear")
async def clear_kb_chat(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    conv_id = _kb_conv_id(kb_id)

    from core.rag_graph import clear_rag_checkpointer
    await clear_rag_checkpointer(conv_id)

    cleared = await clear_kb_messages(conv_id)

    return {"cleared": True, "kb_id": kb_id, "messages_removed": cleared}


# ── KB Chat Messages ────────────────────────────────────────────

@router.get("/bases/{kb_id}/chat/messages")
async def get_kb_chat_messages(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    conv_id = _kb_conv_id(kb_id)
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


# ── RAG Generate Article (SSE stream) ──────────────────────────

class KBGenerateRequest(BaseModel):
    message: str = ""
    style: str = "wechat_mp"
    doc_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=20)


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
        query_vec = await embedding_client.embed_query_async(query)
    except Exception as e:
        raise HTTPException(500, f"Embedding failed: {e}")

    hits = vector_store.search(query_vec, top_k=req.top_k, doc_ids=req.doc_ids or None)
    if not hits:
        chunk_data = {}
        filtered_hits = []
    else:
        chunk_ids = [cid for cid, _ in hits]
        score_map = {cid: score for cid, score in hits}
        chunk_data = await load_kb_chunk_texts(chunk_ids)
        filtered_hits = [(cid, score_map[cid]) for cid in chunk_ids if cid in chunk_data]

    context_parts = []
    for cid, _ in filtered_hits:
        cd = chunk_data[cid]
        page_info = f", 第{cd['page']}页" if cd.get("page", 0) > 0 else ""
        context_parts.append(f"[来源: {cd['filename']}{page_info}]\n{cd['text']}")

    context_text = "\n\n".join(context_parts) if context_parts else "（未检索到相关内容）"

    style_labels = {"xiaohongshu": "小红书", "wechat_mp": "微信公众号", "douyin": "抖音"}
    style_label = style_labels.get(req.style, req.style)

    context_text = "\n\n".join(context_parts) if context_parts else "（未检索到相关内容）"
    # 截断过长的上下文
    if len(context_text) > MAX_RAG_CONTEXT_CHARS:
        context_text = context_text[:MAX_RAG_CONTEXT_CHARS] + "\n\n...（内容过长，已截断）"

    full_system = prompt_manager.kb_generate_system_prompt + f"\n\n【知识库内容】\n{context_text}"

    style_hints = prompt_manager.kb_style_hints

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
            temperature=TEMPERATURE_GENERATE,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            timeout=120,
            max_retries=2,
        )

        prompt_text = f"[System]\n{full_system}\n\n[User]\n{human}"
        yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"

        sources = [{"filename": chunk_data[cid]["filename"], "page": chunk_data[cid].get("page", 0), "score": round(score, 4), "text": chunk_data[cid]["text"], "preview": chunk_data[cid]["text"][:80] + ("..." if len(chunk_data[cid]["text"]) > 80 else "")}
                   for cid, score in filtered_hits]
        if sources:
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"

        messages = [
            SystemMessage(content=full_system),
            HumanMessage(content=human),
        ]

        conv_id = _kb_conv_id(kb_id)

        full_content = ""
        try:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_content += chunk.content
                    data = json.dumps({"type": "chunk", "content": chunk.content}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        if full_content:
            msg_id = uuid.uuid4().hex[:12]
            await save_message({
                "msg_id": msg_id,
                "conv_id": conv_id,
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
            query_vec = await embedding_client.embed_query_async(query)
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
