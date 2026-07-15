"""Knowledge base API routes: KB CRUD, upload, list, delete, search, RAG chat, RAG generate, conversations."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openai import OpenAI as LLMClient
from pydantic import BaseModel, Field

from config import (
    KB_EMBEDDING_DIM,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    MAX_RAG_CONTEXT_CHARS,
    MAX_UPLOAD_SIZE,
    TEMPERATURE_GENERATE,
    UPLOAD_DIR,
)
from core.langsmith_utils import build_langsmith_config
from core.style_manager import build_prompt_display_text, prompt_manager
from database import (
    clear_kb_messages,
    create_conversation,
    create_kb,
    delete_conversation,
    delete_kb_doc,
    load_conversations,
    load_kb,
    load_kb_chunk_texts,
    load_kb_docs,
    load_kbs,
    load_messages,
    rename_kb_doc,
    save_kb_chunks,
    save_kb_doc,
    save_message,
)
from database import (
    delete_kb as db_delete_kb,
)
from database import (
    update_kb as db_update_kb,
)
from rag.chunker import TextChunker
from rag.embeddings import DashScopeEmbedding
from rag.loader import DocumentLoader
from rag.vectorstore import VectorStoreManager

from .errors import not_found, server_error
from .sse import sse_error

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


def _build_rag_prompt_text(
    system_prompt: str,
    context: str,
    message: str,
    doc_meta: str = "",
    web_ctx: str = "",
) -> str:
    """构建RAG系统提示展示文本（用于前端prompt事件）。"""
    return build_prompt_display_text(
        system_prompt,
        message,
        [
            ("", doc_meta),
            ("【知识库内容】", context),
            ("【联网搜索结果】", web_ctx),
        ],
    )


def _summarize_text(
    client: LLMClient,
    text: str,
    *,
    run_name: str,
    max_chars: int = 3000,
) -> str:
    """使用 LLM 生成文档摘要，供文本入库与文件入库共用。"""
    from core.langsmith_utils import traceable

    @traceable(run_name, tags=["kb_upload"], metadata={"model": LLM_MODEL})
    def _call(t: str) -> str:
        completion = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt_manager.doc_summary_system_prompt},
                {"role": "user", "content": t},
            ],
        )
        return (completion.choices[0].message.content or "").strip()

    return _call(text[:max_chars])


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
        not_found("Knowledge base not found")
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
        not_found("Knowledge base not found")
    return kb


@router.delete("/bases/{kb_id}")
async def delete_knowledge_base(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        not_found("Knowledge base not found")

    _ = await db_delete_kb(kb_id)
    vs_manager.remove(kb_id)

    kb_dir = Path(UPLOAD_DIR) / kb_id
    if kb_dir.exists():
        for f in kb_dir.iterdir():
            f.unlink(missing_ok=True)
        try:
            kb_dir.rmdir()
        except Exception as e:
            # 目录非空或被占用时删除失败：数据已清，残留空目录不影响功能，仅记日志。
            logger.warning("Failed to rmdir KB dir %s: %s", kb_dir, e)

    return {"deleted": True, "kb_id": kb_id}


# ── Upload ──────────────────────────────────────────────────────


async def _ingest_text(
    kb_id: str,
    filename: str,
    text: str,
    source_url: str = "",
) -> dict:
    """将一段纯文本入库为知识库文档（不复用文件解析，直接分块+向量化+落库）。

    用于联网搜索结果等"无文件来源"的文本入库。filename 用作展示名（已清洗），
    file_type 固定为 .md，不写文件到 uploads/{kb_id}/ 目录。
    """
    if not text.strip():
        raise HTTPException(400, "内容为空，无法入库")

    from config import LLM_API_KEY, LLM_BASE_URL
    from rag.loader import PageText

    doc_id = uuid.uuid4().hex[:16]

    doc_summary = ""
    try:
        llm_client = LLMClient(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=30.0, max_retries=2)
        doc_summary = _summarize_text(llm_client, text, run_name="kb: doc_summary (text)")
    except Exception as e:
        logger.warning("Summary generation failed for %s: %s", doc_id, e)

    chunks = chunker.chunk_with_pages([PageText(page=1, text=text)], doc_id=doc_id)
    if not chunks:
        raise HTTPException(400, "内容过短，无法分块")

    try:
        vectors = await embedding_client.embed_async([c.text for c in chunks])
    except Exception as e:
        server_error("Embedding failed", e)

    chunk_ids = [c.chunk_id for c in chunks]
    await vs_manager.add_async(kb_id, chunk_ids, vectors, doc_id)

    doc_record = {
        "doc_id": doc_id,
        "kb_id": kb_id,
        "filename": filename,
        "file_type": ".md",
        "chunk_count": len(chunks),
        "file_size": len(text.encode("utf-8")),
        "upload_time": "",
        "status": "ready",
        "summary": doc_summary,
    }
    if source_url:
        doc_record["source_url"] = source_url
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

    return {
        "doc_id": doc_id,
        "filename": filename,
        "chunk_count": len(chunks),
        "file_size": doc_record["file_size"],
    }


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
        server_error("Failed to parse document", e)

    if not doc.text.strip():
        save_path.unlink(missing_ok=True)
        raise HTTPException(400, "Document has no extractable text")

    from openai import OpenAI as LLMClient

    from config import LLM_API_KEY, LLM_BASE_URL

    doc_summary = ""
    try:
        llm_client = LLMClient(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=30.0, max_retries=2)
        doc_summary = _summarize_text(llm_client, doc.text, run_name="kb: doc_summary (file)")
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
        server_error("Embedding failed", e)

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
        not_found("Knowledge base not found")

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


# ── Web Search (standalone, save-to-KB) ─────────────────────────


class KBWebSearchRequest(BaseModel):
    query: str


@router.post("/bases/{kb_id}/web-search")
async def kb_web_search(kb_id: str, req: KBWebSearchRequest):
    kb = await load_kb(kb_id)
    if not kb:
        not_found("Knowledge base not found")
    if not req.query.strip():
        raise HTTPException(400, "搜索词不能为空")

    from tools.web_search import get_web_search_tool, web_search_structured

    if get_web_search_tool() is None:
        raise HTTPException(503, "联网搜索未启用或未配置 API Key")

    try:
        results = await web_search_structured(req.query)
    except Exception as e:
        logger.exception("KB web-search failed: %s", e)
        server_error("联网搜索失败", e)

    return {"results": results}


class KBIngestTextItem(BaseModel):
    title: str
    content: str
    url: str = ""
    filename: str = ""


class KBIngestTextRequest(BaseModel):
    items: list[KBIngestTextItem]


@router.post("/bases/{kb_id}/ingest-text")
async def kb_ingest_text(kb_id: str, req: KBIngestTextRequest):
    kb = await load_kb(kb_id)
    if not kb:
        not_found("Knowledge base not found")
    if not req.items:
        raise HTTPException(400, "没有可入库的内容")

    async def _ingest_one(item):
        title = (item.title or "").strip() or "未命名"
        content = (item.content or "").strip()
        if not content:
            return {"ok": False, "title": title, "detail": "内容为空"}
        filename = (item.filename or "").strip() or f"{title}.md"
        # 清洗文件名，避免非法字符
        safe_filename = re.sub(r'[\\/:*?"<>|\n\r\t]', "_", filename)
        try:
            result = await _ingest_text(kb_id, safe_filename, content, item.url)
            return {"ok": True, "result": result}
        except HTTPException as e:
            return {"ok": False, "title": title, "detail": e.detail}
        except Exception as e:
            return {"ok": False, "title": title, "detail": str(e)}

    outcomes = await asyncio.gather(*(_ingest_one(item) for item in req.items))
    results = []
    errors = []
    for o in outcomes:
        if o.get("ok"):
            results.append(o["result"])
        else:
            errors.append({"title": o.get("title", ""), "detail": o.get("detail", "未知错误")})

    return {"results": results, "errors": errors}


# ── List ────────────────────────────────────────────────────────


@router.get("/bases/{kb_id}/documents")
async def list_documents(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        not_found("Knowledge base not found")
    docs = await load_kb_docs(kb_id)
    total_chunks = sum(d.get("chunk_count", 0) for d in docs)
    return {"documents": docs, "total_chunks": total_chunks}


# ── Delete ──────────────────────────────────────────────────────


@router.get("/bases/{kb_id}/documents/{doc_id}")
async def get_document(kb_id: str, doc_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        not_found("Knowledge base not found")
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
        not_found("Knowledge base not found")
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
        not_found("Knowledge base not found")

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
        not_found("Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        return {"results": [], "total": 0}

    try:
        query_vec = await embedding_client.embed_query_async(req.query)
    except Exception as e:
        server_error("Embedding query failed", e)

    hits = vector_store.search(query_vec, top_k=req.top_k, doc_ids=req.doc_ids or None)
    if not hits:
        return {"results": [], "total": 0}

    chunk_ids = [cid for cid, _ in hits]
    score_map = dict(hits)
    chunk_data = await load_kb_chunk_texts(chunk_ids)

    results = []
    for cid in chunk_ids:
        if cid in chunk_data:
            cd = chunk_data[cid]
            preview = cd["text"][:120] + ("..." if len(cd["text"]) > 120 else "")
            results.append(
                {
                    "chunk_id": cid,
                    "doc_id": cd["doc_id"],
                    "filename": cd["filename"],
                    "page": cd["page"],
                    "text": cd["text"],
                    "preview": preview,
                    "score": round(score_map.get(cid, 0), 4),
                }
            )

    return {"results": results, "total": len(results)}


@router.get("/bases/{kb_id}/suggestions")
async def get_suggestions(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        not_found("Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        return {"suggestions": []}

    docs = await load_kb_docs(kb_id)
    summaries = [d.get("summary", "") for d in docs if d.get("summary")]
    doc_names = [d["filename"] for d in docs]

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    try:
        llm = ChatOpenAI(
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            timeout=30,
            max_retries=2,
        )
        context = ""
        if summaries:
            context = "文档概要：\n" + "\n".join(f"- {s}" for s in summaries[:5])
        else:
            context = "文档列表：" + "、".join(doc_names[:10])

        messages = [
            SystemMessage(content=prompt_manager.question_generator_system_prompt),
            HumanMessage(content=context),
        ]
        text = (await llm.ainvoke(messages)).content or ""
        text = text.strip()
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
        not_found("Knowledge base not found")
    conv_id = uuid.uuid4().hex[:12]
    await create_conversation({"conv_id": conv_id, "kb_id": kb_id, "title": req.title})
    return {"conv_id": conv_id, "kb_id": kb_id, "title": req.title}


@router.get("/bases/{kb_id}/conversations")
async def list_conversations(kb_id: str):
    kb = await load_kb(kb_id)
    if not kb:
        not_found("Knowledge base not found")
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
            except Exception as e:
                # sources JSON 损坏时静默降级为空，避免整条消息渲染失败；记日志便于排查脏数据。
                logger.warning("Failed to parse sources JSON for message: %s", e)
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
    await save_message(
        {
            "msg_id": msg_id,
            "conv_id": conv_id,
            "role": req.role,
            "content": req.content,
            "type": req.type,
            "sources": json.dumps(req.sources, ensure_ascii=False) if req.sources else "",
        }
    )
    return {"msg_id": msg_id}


STYLE_LABELS = {"xiaohongshu": "小红书", "wechat_mp": "微信公众号", "douyin": "抖音"}


def _style_hint(style: str) -> str:
    hints = {
        "xiaohongshu": "请用小红书风格生成：emoji开头标题、短段落口语化、关键数字用类比、结尾互动引导+话题标签、800字以内",
        "wechat_mp": "请用公众号风格生成：简洁有力标题、开头用数据切入、分2-4节含事实+逻辑+数据、影响研判、前瞻判断、1200-1800字",
        "douyin": "请用抖音风格生成：极简数字标题、短平快每句不超20字、3个要点节奏感、数字口语化、200-300字",
    }
    return hints.get(style, "")


async def _stream_kb_article(
    kb_id: str,
    query: str,
    style: str,
    doc_ids: list[str],
    top_k: int,
    conv_id: str,
):
    """共享知识库文章生成流式逻辑。

    Yields SSE data lines. Caller should wrap in StreamingResponse.
    生成完成后会自动将 user 与 assistant 消息以 type='article' 写入 kb_messages，
    并将历史会话作为上下文喂给 LLM，使生成能延续之前的要求与文章。
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        yield sse_error("知识库为空，请先上传文档")
        return

    # 确保会话存在
    existing_convs = await load_conversations(kb_id)
    if not any(c["conv_id"] == conv_id for c in existing_convs):
        kb = await load_kb(kb_id)
        title = kb["name"] if kb else "知识库会话"
        await create_conversation({"conv_id": conv_id, "kb_id": kb_id, "title": title})

    style_label = STYLE_LABELS.get(style, style)
    hint = _style_hint(style)

    # 用户本次输入：query 由 endpoint 传入，空则给一个默认指令（不依赖前端必须填）
    raw_query = (query or "").strip()
    has_user_input = bool(raw_query)
    default_query = "总结知识库核心内容"
    # 用于检索的 query：只包含语义内容（用户原话 + 历史），不掺入风格提示噪音，
    # 否则 embedding 会被「emoji/口语化/话题标签」等风格词带偏，召回与知识库无关。
    retrieval_query = raw_query or default_query

    # 仅当用户真实输入时才保存 user 消息，避免历史里堆积「总结知识库核心内容」之类的占位
    user_msg_id = uuid.uuid4().hex[:12]
    if has_user_input:
        await save_message(
            {
                "msg_id": user_msg_id,
                "conv_id": conv_id,
                "role": "user",
                "content": raw_query,
                "type": "article",
                "sources": "",
            }
        )

    # 加载历史会话作为上下文（仅取最近 50 条，避免长会话上下文爆炸）
    history_msgs = await load_messages(conv_id, limit=50)
    prior_history = []
    for m in history_msgs:
        if m.get("msg_id") == user_msg_id:
            continue
        role = m.get("role")
        content = m.get("content") or ""
        if not content:
            continue
        if role == "user":
            prior_history.append(HumanMessage(content=content))
        elif role == "assistant":
            prior_history.append(AIMessage(content=content))

    # 检索查询：将历史最近几轮 + 本次用户输入合并，提升对知识库的召回相关性
    if prior_history:
        recent = prior_history[-4:]  # 最近 4 条历史
        hist_text = "\n".join(("用户：" if isinstance(m, HumanMessage) else "AI：") + m.content for m in recent)
        retrieval_query = f"{hist_text}\n用户：{raw_query or default_query}"

    # 发给 LLM 的用户消息：包含原话（或默认指令）+ 风格提示
    user_text = raw_query or f"请基于知识库内容生成一篇{style_label}风格的文章"
    if hint:
        user_text = f"{user_text}\n\n{hint}"

    try:
        query_vec = await embedding_client.embed_query_async(retrieval_query)
    except Exception as e:
        yield sse_error(f"Embedding failed: {e}")
        return

    hits = vector_store.search(query_vec, top_k=top_k, doc_ids=doc_ids or None)
    if not hits:
        chunk_data = {}
        filtered_hits = []
    else:
        chunk_ids = [cid for cid, _ in hits]
        score_map = dict(hits)
        chunk_data = await load_kb_chunk_texts(chunk_ids)
        filtered_hits = [(cid, score_map[cid]) for cid in chunk_ids if cid in chunk_data]

    context_parts = []
    for idx, (cid, _) in enumerate(filtered_hits, start=1):
        cd = chunk_data[cid]
        page_info = f", 第{cd['page']}页" if cd.get("page", 0) > 0 else ""
        context_parts.append(f"[来源{idx}: {cd['filename']}{page_info}]\n{cd['text']}")

    context_text = "\n\n".join(context_parts) if context_parts else "（未检索到相关内容）"
    if len(context_text) > MAX_RAG_CONTEXT_CHARS:
        context_text = context_text[:MAX_RAG_CONTEXT_CHARS] + "\n\n...（内容过长，已截断）"

    full_system = prompt_manager.kb_generate_system_prompt + f"\n\n【知识库内容】\n{context_text}"

    llm = ChatOpenAI(
        model=LLM_MODEL,
        temperature=TEMPERATURE_GENERATE,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        timeout=120,
        max_retries=2,
    )

    # 通知前端这是一条可发布的文章消息
    yield f"data: {json.dumps({'type': 'meta', 'message_type': 'article'}, ensure_ascii=False)}\n\n"

    prompt_text = build_prompt_display_text(full_system, user_text)
    yield f"data: {json.dumps({'type': 'prompt', 'content': prompt_text}, ensure_ascii=False)}\n\n"

    sources = [
        {
            "filename": chunk_data[cid]["filename"],
            "page": chunk_data[cid].get("page", 0),
            "score": round(score, 4),
            "text": chunk_data[cid]["text"],
            "preview": chunk_data[cid]["text"][:80] + ("..." if len(chunk_data[cid]["text"]) > 80 else ""),
        }
        for cid, score in filtered_hits
    ]
    if sources:
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"

    # 组装 LLM 消息：系统提示（含知识库内容） + 历史会话 + 本次用户输入
    messages = [SystemMessage(content=full_system)]
    if prior_history:
        # 截断历史，避免上下文过长
        messages.extend(prior_history[-10:])
    messages.append(HumanMessage(content=user_text))

    full_content = ""
    try:
        async for chunk in llm.astream(messages):
            if chunk.content:
                full_content += chunk.content
                data = json.dumps({"type": "chunk", "content": chunk.content}, ensure_ascii=False)
                yield f"data: {data}\n\n"
    except Exception as e:
        yield sse_error(str(e))

    if full_content:
        msg_id = uuid.uuid4().hex[:12]
        await save_message(
            {
                "msg_id": msg_id,
                "conv_id": conv_id,
                "role": "assistant",
                "content": full_content,
                "type": "article",
                "sources": json.dumps(sources, ensure_ascii=False) if sources else "",
            }
        )

    yield "data: [DONE]\n\n"


# ── RAG Chat (SSE stream, with short-term memory) ──────────────


class KBChatRequest(BaseModel):
    message: str
    doc_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=20)
    web_search: bool = False
    conv_id: str = ""


def _kb_conv_id(kb_id: str) -> str:
    return f"kb_{kb_id}"


@router.post("/bases/{kb_id}/chat/stream")
async def kb_chat_stream(kb_id: str, req: KBChatRequest):
    kb = await load_kb(kb_id)
    if not kb:
        not_found("Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        raise HTTPException(400, "Knowledge base is empty. Please upload documents first.")

    conv_id = req.conv_id or _kb_conv_id(kb_id)

    existing_convs = await load_conversations(kb_id)
    if not any(c["conv_id"] == conv_id for c in existing_convs):
        await create_conversation({"conv_id": conv_id, "kb_id": kb_id, "title": kb["name"]})

    from core.rag_graph import get_rag_graph, migrate_history

    rag_graph = await get_rag_graph()

    # LangSmith 元数据：run_name 在 UI 列表直接显示用户问题；tags 支持按知识库/特征筛选；
    # metadata 记录排查所需的上下文（模型、知识库、检索参数等）
    query_preview = req.message.replace("\n", " ")[:80]
    config = build_langsmith_config(
        thread_id=conv_id,
        run_name=f"kb_chat: {query_preview}" if query_preview else "kb_chat",
        tags=["kb_chat", f"kb:{kb['name']}"],
        metadata={
            "conversation_id": conv_id,
            "feature": "kb_chat",
            "kb_id": kb_id,
            "kb_name": kb["name"],
            "user_query": req.message[:200],
            "model": LLM_MODEL,
            "doc_ids": req.doc_ids,
            "top_k": req.top_k,
            "web_search": req.web_search,
        },
    )

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

        # 联网搜索：开启时先搜索，结果走 web_context state 字段（不拼进 query，避免污染检索）
        # 始终写入 web_context（含空串）以覆盖 checkpointer 中上一轮残留值，防泄漏
        web_ctx = ""
        if req.web_search:
            from tools.web_search import get_web_search_tool

            ws_tool = get_web_search_tool()
            if ws_tool:
                yield f"data: {json.dumps({'type': 'loading', 'message': '正在联网搜索...'}, ensure_ascii=False)}\n\n"
                try:
                    web_ctx = await ws_tool.ainvoke({"query": req.message})
                except Exception as e:
                    logger.exception("KB web_search failed: %s", e)
                    web_ctx = ""  # 优雅降级：KB-only 回答
        input_state["web_context"] = web_ctx

        msg_id = uuid.uuid4().hex[:12]
        await save_message(
            {
                "msg_id": msg_id,
                "conv_id": conv_id,
                "role": "user",
                "content": req.message,
                "type": "chat",
                "sources": "",
            }
        )

        try:
            async for event in rag_graph.astream_events(input_state, config=config, version="v2"):
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
                    doc_meta = output.get("doc_meta", "")
                    intent = output.get("intent", "specific")
                    # 根据意图选择展示的系统提示
                    system_for_display = (
                        prompt_manager.kb_rag_summary_system_prompt
                        if intent == "summary" and doc_meta
                        else prompt_manager.kb_rag_system_prompt
                    )
                    prompt_text = _build_rag_prompt_text(
                        system_for_display, context_text, req.message, doc_meta, web_ctx
                    )
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
                        intent = (cur_state.values or {}).get("intent", "specific")
                        doc_meta = (cur_state.values or {}).get("doc_meta", "")
                        system_for_display = (
                            prompt_manager.kb_rag_summary_system_prompt
                            if intent == "summary" and doc_meta
                            else prompt_manager.kb_rag_system_prompt
                        )
                        prompt_text = _build_rag_prompt_text(
                            system_for_display, last_context, req.message, doc_meta, web_ctx
                        )
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
                # 兜底：未触发流式事件时补充 user prompt（反斜杠提取到变量，规避 Py3.11 f-string 限制）
                user_prompt = f"[User]\n{req.message}"
                yield f"data: {json.dumps({'type': 'prompt', 'content': user_prompt}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield sse_error(str(e))

        if full_content:
            asst_msg_id = uuid.uuid4().hex[:12]
            await save_message(
                {
                    "msg_id": asst_msg_id,
                    "conv_id": conv_id,
                    "role": "assistant",
                    "content": full_content,
                    "type": "chat",
                    "sources": json.dumps(sources_out, ensure_ascii=False) if sources_out else "",
                }
            )

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
        not_found("Knowledge base not found")

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
        not_found("Knowledge base not found")

    conv_id = _kb_conv_id(kb_id)
    msgs = await load_messages(conv_id)
    for m in msgs:
        if m.get("sources"):
            try:
                m["sources"] = json.loads(m["sources"])
            except Exception as e:
                # sources JSON 损坏时静默降级为空，避免整条消息渲染失败；记日志便于排查脏数据。
                logger.warning("Failed to parse sources JSON for message: %s", e)
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
    conv_id: str = ""


@router.post("/bases/{kb_id}/generate/stream")
async def kb_generate_stream(kb_id: str, req: KBGenerateRequest):
    kb = await load_kb(kb_id)
    if not kb:
        not_found("Knowledge base not found")

    vector_store = vs_manager.get(kb_id)
    if vector_store.total_vectors == 0:
        raise HTTPException(400, "Knowledge base is empty. Please upload documents first.")

    # 空输入时原样下传，由 _stream_kb_article 统一兜底默认值并决定是否保存 user 消息；
    # 在此处提前替换会架空下游 has_user_input 判断，导致占位 query 被当真实输入存进历史，
    # 后续生成会因历史 + 本次叠加而在一次 LLM 调用里出现重复 User 消息。
    query = req.message
    # 生成文章使用独立会话命名空间，与问答会话（kb_{kb_id} / UUID）物理隔离
    conv_id = req.conv_id or f"gen_{kb_id}"

    async def event_stream():
        async for data in _stream_kb_article(kb_id, query, req.style, req.doc_ids, req.top_k, conv_id):
            yield data

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
        except Exception as e:
            # 嵌入失败跳过该知识库，避免拖垮整批检索；记日志便于定位嵌入服务问题。
            logger.warning("Embedding query failed for KB %s during internal search: %s", kb["kb_id"], e)
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
                all_results.append(
                    f"[知识库: {kb['name']}, 来源: {cd['filename']}{page_info}, 相关度: {score:.2f}]\n{cd['text']}"
                )

    if not all_results:
        return "未在知识库中找到与查询相关的内容。"

    return "\n\n".join(all_results)
