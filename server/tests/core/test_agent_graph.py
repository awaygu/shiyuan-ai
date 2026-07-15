"""core/agent_graph.py 测试：build_agent / get_checkpointer / get_agent_llm / get_summary_llm。

mock create_agent 避免真实 LLM 调用。get_checkpointer 是单例，测试间需清理。
"""

from __future__ import annotations

import pytest

import core.agent_graph as ag


@pytest.fixture(autouse=True)
def _reset_checkpointer_singleton(monkeypatch, tmp_path):
    """每个测试重置 checkpointer 单例，并用独立 MEMORY_DB_PATH。"""
    monkeypatch.setattr(ag, "MEMORY_DB_PATH", str(tmp_path / "agent_memory.db"))
    monkeypatch.setattr(ag, "_checkpointer", None)
    monkeypatch.setattr(ag, "_checkpointer_ctx", None)
    yield
    # 清理：关闭单例连接
    import asyncio

    if ag._checkpointer_ctx is not None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(ag._checkpointer_ctx.__aexit__(None, None, None))
        except Exception:
            pass
        finally:
            loop.close()


async def test_get_checkpointer_returns_singleton():
    cp1 = await ag.get_checkpointer()
    cp2 = await ag.get_checkpointer()
    assert cp1 is cp2  # 单例：第二次直接返回缓存


async def test_get_checkpointer_creates_sqlite_saver():
    cp = await ag.get_checkpointer()
    assert cp is not None


def test_get_agent_llm_uses_config():
    """get_agent_llm 返回 ChatOpenAI，参数来自 config。"""
    llm = ag.get_agent_llm()
    assert llm is not None
    # ChatOpenAI 的 model_name / temperature 应反映 config
    from config import LLM_MODEL

    assert llm.model_name == LLM_MODEL


def test_get_summary_llm_uses_config():
    llm = ag.get_summary_llm()
    assert llm is not None
    from config import SUMMARY_MODEL

    assert llm.model_name == SUMMARY_MODEL


async def test_build_agent_returns_compiled_graph(monkeypatch):
    """build_agent 用 mock create_agent，返回其结果并记录参数。"""
    captured = {}

    class _FakeAgent:
        pass

    def _fake_create_agent(*, model, tools, system_prompt, middleware, checkpointer):
        captured["model"] = model
        captured["tools"] = tools
        captured["system_prompt"] = system_prompt
        captured["middleware"] = middleware
        captured["checkpointer"] = checkpointer
        return _FakeAgent()

    monkeypatch.setattr(ag, "create_agent", _fake_create_agent)

    result = await ag.build_agent(tools=["t1"], system_prompt="sys prompt")
    assert isinstance(result, _FakeAgent)
    assert captured["tools"] == ["t1"]
    assert captured["system_prompt"] == "sys prompt"
    # checkpointer 来自 get_checkpointer
    assert captured["checkpointer"] is await ag.get_checkpointer()
    # middleware 含一个 SummarizationMiddleware
    assert len(captured["middleware"]) == 1


async def test_build_agent_passes_summary_middleware_with_config(monkeypatch):
    """SummarizationMiddleware 用 config 的 trigger/keep 值。"""
    from langchain.agents.middleware import SummarizationMiddleware

    captured = {}

    def _fake_create_agent(*, model, tools, system_prompt, middleware, checkpointer):
        captured["middleware"] = middleware
        return object()

    monkeypatch.setattr(ag, "create_agent", _fake_create_agent)
    await ag.build_agent(tools=[], system_prompt="s")
    mw = captured["middleware"][0]
    assert isinstance(mw, SummarizationMiddleware)
