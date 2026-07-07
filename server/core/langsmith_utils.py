"""裸 SDK LLM 调用的 LangSmith tracing 适配层。

LangChain/LangGraph 调用由 langchain-langsmith 自动追踪（依赖 .env 中
LANGSMITH_* 环境变量）。但多处代码绕过 LangChain，直接用裸 openai /
dashscope / httpx 调模型——这里提供受配置门控的 ``traceable`` 装饰器，
把这些调用也接入 LangSmith trace。

tracing 关闭时（LANGSMITH_TRACING=false）退化为透传装饰器且不导入 langsmith，
行为与现状完全一致。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from config import LANGSMITH_TRACING

if LANGSMITH_TRACING:
    from langsmith import traceable as _traceable
else:
    _traceable = None  # type: ignore[assignment]


def build_langsmith_config(
    thread_id: str,
    run_name: str,
    tags: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """构造 LangGraph/LangSmith 运行配置。

    统一封装 ``configurable/thread_id``、``run_name``、``tags``、``metadata``，
    避免 agent/knowledge 等 endpoint 重复组装相同结构。
    """
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": run_name,
        "tags": tags,
        "metadata": metadata,
    }


def traceable(
    name: str,
    *,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """语义化包装裸 SDK 调用，使其在 LangSmith 中可见。

    Args:
        name: run 名称，建议形如 ``"kb: doc_summary"``，UI 列表可直接看到。
        tags: 筛选用标签，如 ``["kb_upload"]``。
        metadata: 排查所需的上下文，如 ``{"model": ..., "kb_id": ...}``。

    Returns:
        装饰器。关闭时透传原函数（保留签名/docstring）；开启时透传给
        ``langsmith.traceable``。
    """
    if not LANGSMITH_TRACING or _traceable is None:
        def _passthrough(fn: Callable[..., Any]) -> Callable[..., Any]:
            # 透传：保持原函数不变，无任何 LangSmith 副作用。
            return fn

        return _passthrough

    return _traceable(name=name, tags=tags or [], metadata=metadata or {})
