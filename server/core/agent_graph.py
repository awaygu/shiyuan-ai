"""LangGraph Agent 定义 — 使用 create_agent + SummarizationMiddleware。

核心组件：
- create_agent: LangChain v1 标准 Agent 构建方式
- SummarizationMiddleware: token 超限时自动摘要压缩历史
- AsyncSqliteSaver: LangGraph 异步 checkpointer，持久化 agent 状态
"""

from __future__ import annotations

import logging

import aiosqlite
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    SUMMARY_MODEL,
    SUMMARY_MODEL_BASE_URL,
    SUMMARY_MODEL_API_KEY,
    TEMPERATURE_ANALYZE,
    TEMPERATURE_SUMMARY,
    SUMMARY_TRIGGER_TOKENS,
    SUMMARY_KEEP_MESSAGES,
    MEMORY_DB_PATH,
)

logger = logging.getLogger(__name__)

# 全局 AsyncSqliteSaver 单例及其 context manager
_checkpointer_ctx = None
_checkpointer: AsyncSqliteSaver | None = None


async def get_checkpointer() -> AsyncSqliteSaver:
    """获取全局 AsyncSqliteSaver 实例（单例）。

    from_conn_string 是 async context manager，
    我们保持其打开直到进程退出。
    """
    global _checkpointer, _checkpointer_ctx
    if _checkpointer is None:
        _checkpointer_ctx = AsyncSqliteSaver.from_conn_string(MEMORY_DB_PATH)
        _checkpointer = await _checkpointer_ctx.__aenter__()
    return _checkpointer


def get_agent_llm() -> ChatOpenAI:
    """获取 Agent 主 LLM。"""
    return ChatOpenAI(
        model="deepseek-chat",
        temperature=TEMPERATURE_ANALYZE,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        timeout=120,
        max_retries=2,
    )


def get_summary_llm() -> ChatOpenAI:
    """获取摘要 LLM。"""
    return ChatOpenAI(
        model=SUMMARY_MODEL,
        temperature=TEMPERATURE_SUMMARY,
        api_key=SUMMARY_MODEL_API_KEY,
        base_url=SUMMARY_MODEL_BASE_URL,
        timeout=60,
        max_retries=1,
    )


async def build_agent(tools: list, system_prompt: str):
    """构建 LangGraph Agent。

    Args:
        tools: LangChain tool 列表
        system_prompt: 系统 prompt

    Returns:
        CompiledStateGraph — 可 astream_events 的 Agent
    """
    agent_llm = get_agent_llm()
    summary_llm = get_summary_llm()
    checkpointer = await get_checkpointer()

    agent = create_agent(
        model=agent_llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[
            SummarizationMiddleware(
                model=summary_llm,
                trigger=("tokens", SUMMARY_TRIGGER_TOKENS),
                keep=("messages", SUMMARY_KEEP_MESSAGES),
            )
        ],
        checkpointer=checkpointer,
    )

    logger.info(
        "Agent built: summary_trigger=%d tokens, keep=%d messages",
        SUMMARY_TRIGGER_TOKENS,
        SUMMARY_KEEP_MESSAGES,
    )
    return agent
