"""KB RAG LangGraph — 短期记忆 + 查询重写 + 摘要压缩。

核心组件：
- StateGraph: rewrite_query → retrieve → generate
- 规则前置过滤：代词/短句/祈使句命中才触发 LLM 查询重写
- SummarizationMiddleware：对话历史 token 超限时自动摘要压缩
- AsyncSqliteSaver：独立 rag_memory.db，持久化 graph state
- 检索内容不入历史（策略 B），仅 Human/AIMessage 持久化
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from config import (
    KB_RAG_MEMORY_DB_PATH,
    KB_RAG_SUMMARY_KEEP_MESSAGES,
    KB_RAG_SUMMARY_TRIGGER_TOKENS,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    SUMMARY_MODEL,
    SUMMARY_MODEL_API_KEY,
    SUMMARY_MODEL_BASE_URL,
    TEMPERATURE_REWRITE,
    TEMPERATURE_SUMMARY,
    TEMPERATURE_CHAT,
    MAX_RAG_CONTEXT_CHARS,
)
from core.style_manager import prompt_manager

logger = logging.getLogger(__name__)

# ── Rule-based follow-up detection ───────────────────────────────

_FOLLOWUP_PRONOUN_RE = re.compile(
    r"(那|它|这|上述|刚才|前文|这个|那个|上面|之前|上次|刚才提到的|前面说的)"
)
_FOLLOWUP_SHORT_RE = re.compile(r"^[^，。！？\n]{1,14}$")
_FOLLOWUP_EXPLAIN_RE = re.compile(
    r"(详细|展开|深入|具体|再|进一步|补充|解释|说明|阐述| elaborat|more detail)"
)


def should_rewrite(query: str) -> bool:
    if _FOLLOWUP_PRONOUN_RE.search(query):
        return True
    if _FOLLOWUP_SHORT_RE.match(query):
        return True
    if _FOLLOWUP_EXPLAIN_RE.search(query):
        return True
    return False


# ── Summarization Middleware ─────────────────────────────────────


class SummarizationMiddleware:
    """Token 超限时自动摘要压缩历史消息。

    - 计算 messages 中非 SystemMessage 的 token 总数（粗估：中文 1 字 ≈ 1.5 token）
    - 超过 trigger 时，将较早的消息压缩为一条 SystemMessage 摘要
    - 保留最近 keep 条消息不动
    - 保留所有 SystemMessage（包括已有摘要）
    """

    def __init__(
        self,
        model: ChatOpenAI,
        trigger_tokens: int,
        keep_messages: int,
    ):
        self.model = model
        self.trigger_tokens = trigger_tokens
        self.keep_messages = keep_messages

    def _estimate_tokens(self, messages: list[BaseMessage]) -> int:
        total = 0
        for m in messages:
            if isinstance(m, SystemMessage) and m.name == "conversation_summary":
                total += len(m.content) // 3
            else:
                total += int(len(m.content) * 1.5)
        return total

    async def maybe_summarize(
        self, messages: list[BaseMessage]
    ) -> list[BaseMessage]:
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]
        if len(non_system) <= self.keep_messages:
            return messages

        estimated = self._estimate_tokens(non_system)
        if estimated < self.trigger_tokens:
            return messages

        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        conversation_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

        if len(conversation_msgs) <= self.keep_messages:
            return messages

        to_summarize = conversation_msgs[: -self.keep_messages]
        to_keep = conversation_msgs[-self.keep_messages :]

        summary_text = await self._summarize(to_summarize)

        summary_msg = SystemMessage(
            content=f"以下是之前对话的摘要：\n{summary_text}",
            name="conversation_summary",
        )

        new_messages = system_msgs + [summary_msg] + to_keep
        logger.info(
            "SummarizationMiddleware: compressed %d messages → summary (%d chars), kept %d recent",
            len(to_summarize),
            len(summary_text),
            len(to_keep),
        )
        return new_messages

    async def _summarize(self, messages: list[BaseMessage]) -> str:
        conversation_text = ""
        for m in messages:
            role = "用户" if isinstance(m, HumanMessage) else "AI"
            conversation_text += f"{role}: {m.content}\n"

        try:
            resp = await self.model.ainvoke(
                [
                    SystemMessage(
                        content=prompt_manager.conversation_summary_prompt
                    ),
                    HumanMessage(content=conversation_text),
                ]
            )
            return resp.content or ""
        except Exception as e:
            logger.warning("Summarization failed: %s", e)
            return "（对话历史摘要生成失败）"


# ── RAG State ────────────────────────────────────────────────────


def _add_messages(existing: list[BaseMessage], new: list[BaseMessage]) -> list[BaseMessage]:
    return existing + new


class RAGState(dict):
    """KB RAG Graph state — only conversation messages are persisted via checkpointer."""

    messages: Annotated[list[BaseMessage], _add_messages]
    query: str
    rewritten_query: str
    skip_retrieve: bool
    context: str
    sources: list[dict]
    last_context: str
    last_sources: list[dict]
    kb_id: str
    doc_ids: list[str]
    top_k: int


# ── Nodes ────────────────────────────────────────────────────────


async def rewrite_query(state: dict) -> dict:
    query = state.get("query", "")
    messages = state.get("messages", [])

    if not messages:
        return {"rewritten_query": query, "skip_retrieve": False}

    if not should_rewrite(query):
        return {"rewritten_query": query, "skip_retrieve": False}

    recent = messages[-6:] if len(messages) > 6 else messages
    history_text = ""
    for m in recent:
        role = "用户" if isinstance(m, HumanMessage) else "AI"
        history_text += f"{role}: {m.content}\n"

    try:
        rewrite_llm = ChatOpenAI(
            model=SUMMARY_MODEL,
            temperature=TEMPERATURE_REWRITE,
            api_key=SUMMARY_MODEL_API_KEY,
            base_url=SUMMARY_MODEL_BASE_URL,
            timeout=15,
            max_retries=1,
        )
        resp = await rewrite_llm.ainvoke(
            [
                SystemMessage(content=prompt_manager.rewrite_system_prompt),
                HumanMessage(
                    content=f"历史对话：\n{history_text}\n当前用户输入：{query}"
                ),
            ]
        )
        raw = (resp.content or "").strip()
        json_match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            rtype = parsed.get("type", "new_question")
            rewritten = parsed.get("rewritten_query", query)

            if rtype == "follow_up_no_search":
                return {"rewritten_query": query, "skip_retrieve": True}
            elif rtype == "follow_up_need_search":
                return {"rewritten_query": rewritten or query, "skip_retrieve": False}
            else:
                return {"rewritten_query": rewritten or query, "skip_retrieve": False}
    except Exception as e:
        logger.warning("Query rewrite LLM failed: %s, fallback to original query", e)

    return {"rewritten_query": query, "skip_retrieve": False}


async def retrieve(state: dict) -> dict:
    from rag.embeddings import DashScopeEmbedding
    from rag.vectorstore import VectorStoreManager
    from config import KB_EMBEDDING_DIM
    from database import load_kb_chunk_texts

    if state.get("skip_retrieve", False):
        return {
            "context": state.get("last_context", ""),
            "sources": state.get("last_sources", []),
        }

    kb_id = state.get("kb_id", "")
    rewritten_query = state.get("rewritten_query", state.get("query", ""))
    doc_ids = state.get("doc_ids", [])
    top_k = state.get("top_k", 10)

    embedding_client = DashScopeEmbedding()
    vs_manager = VectorStoreManager(dim=KB_EMBEDDING_DIM)

    try:
        query_vec = await embedding_client.embed_query_async(rewritten_query)
    except Exception as e:
        logger.error("Embedding failed in retrieve: %s", e)
        return {"context": "（检索失败）", "sources": []}

    vector_store = vs_manager.get(kb_id)
    hits = vector_store.search(query_vec, top_k=top_k, doc_ids=doc_ids or None)
    if not hits:
        return {"context": "（未检索到相关内容）", "sources": []}

    chunk_ids = [cid for cid, _ in hits]
    score_map = {cid: score for cid, score in hits}

    chunk_data = await load_kb_chunk_texts(chunk_ids)

    filtered_hits = [(cid, score_map[cid]) for cid in chunk_ids if cid in chunk_data]

    context_parts = []
    sources = []
    for cid, score in filtered_hits:
        cd = chunk_data[cid]
        page_info = f", 第{cd['page']}页" if cd.get("page", 0) > 0 else ""
        context_parts.append(f"[来源: {cd['filename']}{page_info}]\n{cd['text']}")
        sources.append(
            {
                "filename": cd["filename"],
                "page": cd.get("page", 0),
                "score": round(score, 4),
                "text": cd["text"],
                "preview": cd["text"][:80] + ("..." if len(cd["text"]) > 80 else ""),
            }
        )

    context_text = "\n\n".join(context_parts) if context_parts else "（未检索到相关内容）"

    return {
        "context": context_text,
        "sources": sources,
        "last_context": context_text,
        "last_sources": sources,
    }


def truncate_context(context: str, max_chars: int = MAX_RAG_CONTEXT_CHARS) -> str:
    """按 chunk 截断上下文，保留最相关的部分，避免超出上下文窗口。

    策略：
    - 优先保留完整的 chunk（每个 chunk 通常是一个文档片段）
    - 如果单个 chunk 就超过上限，截断该 chunk 并保留前 max_chars 字符
    """
    if len(context) <= max_chars:
        return context
    chunks = context.split("\n\n")
    result = []
    current_len = 0
    for chunk in chunks:
        needed = len(chunk) + (2 if result else 0)
        if current_len + needed > max_chars:
            # 如果这是第一个 chunk 且它本身就超长，截断它
            if not result:
                result.append(chunk[:max_chars])
                current_len = max_chars
            break
        result.append(chunk)
        current_len += needed
    logger.warning(
        "Context truncated: %d chars → %d chars (kept %d/%d chunks)",
        len(context), current_len, len(result), len(chunks),
    )
    return "\n\n".join(result)


async def generate(state: dict) -> dict:
    messages = state.get("messages", [])
    query = state.get("query", "")
    context = state.get("context", "")

    summary_llm = ChatOpenAI(
        model=SUMMARY_MODEL,
        temperature=TEMPERATURE_SUMMARY,
        api_key=SUMMARY_MODEL_API_KEY,
        base_url=SUMMARY_MODEL_BASE_URL,
        timeout=60,
        max_retries=1,
    )

    mw = SummarizationMiddleware(
        model=summary_llm,
        trigger_tokens=KB_RAG_SUMMARY_TRIGGER_TOKENS,
        keep_messages=KB_RAG_SUMMARY_KEEP_MESSAGES,
    )
    compressed_messages = await mw.maybe_summarize(messages)

    agent_llm = ChatOpenAI(
        model=LLM_MODEL,
        temperature=TEMPERATURE_CHAT,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        timeout=120,
        max_retries=2,
        streaming=True,
    )

    full_system = prompt_manager.kb_rag_system_prompt + f"\n\n【知识库内容】\n{truncate_context(context)}"

    llm_messages = [SystemMessage(content=full_system)] + compressed_messages + [HumanMessage(content=query)]

    full_content = ""
    async for chunk in agent_llm.astream(llm_messages):
        if chunk.content:
            full_content += chunk.content

    return {
        "messages": [HumanMessage(content=query), AIMessage(content=full_content)],
    }


# ── Graph builder ────────────────────────────────────────────────

_rag_checkpointer_ctx = None
_rag_checkpointer: AsyncSqliteSaver | None = None


async def get_rag_checkpointer() -> AsyncSqliteSaver:
    global _rag_checkpointer, _rag_checkpointer_ctx
    if _rag_checkpointer is None:
        from pathlib import Path
        Path(KB_RAG_MEMORY_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _rag_checkpointer_ctx = AsyncSqliteSaver.from_conn_string(
            KB_RAG_MEMORY_DB_PATH
        )
        _rag_checkpointer = await _rag_checkpointer_ctx.__aenter__()
    return _rag_checkpointer


async def clear_rag_checkpointer(thread_id: str) -> None:
    cp = await get_rag_checkpointer()
    try:
        conn = cp.conn
        conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM checkpoint_blobs WHERE thread_id = ?", (thread_id,))
        conn.commit()
        logger.info("Cleared RAG checkpointer for thread_id=%s", thread_id)
    except Exception:
        logger.warning("Failed to clear RAG checkpointer for thread_id=%s", thread_id, exc_info=True)


def build_rag_graph() -> StateGraph:
    graph = StateGraph(RAGState)

    graph.add_node("rewrite_query", rewrite_query)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)

    graph.add_edge(START, "rewrite_query")
    graph.add_conditional_edges(
        "rewrite_query",
        lambda s: "generate" if s.get("skip_retrieve", False) else "retrieve",
        {"retrieve": "retrieve", "generate": "generate"},
    )
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)

    return graph


_compiled_rag_graph = None


async def get_rag_graph():
    global _compiled_rag_graph
    if _compiled_rag_graph is None:
        graph = build_rag_graph()
        checkpointer = await get_rag_checkpointer()
        _compiled_rag_graph = graph.compile(checkpointer=checkpointer)
        logger.info("RAG graph compiled with checkpointer at %s", KB_RAG_MEMORY_DB_PATH)
    return _compiled_rag_graph


# ── History migration ────────────────────────────────────────────


async def migrate_history(conv_id: str) -> list[BaseMessage]:
    """从 kb_messages 加载旧对话历史，转为 BaseMessage 列表。"""
    from database import load_messages

    old_msgs = await load_messages(conv_id)
    if not old_msgs:
        return []

    result = []
    for m in old_msgs:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
    return result
