"""复现「知识库聊天 RAG 中 LLM 收到重复 User 消息」的 bug。

真实场景（来自 LangSmith trace log/log.txt）：
  用户在知识库聊天界面输入「英伟达Rubin的量产交付对AI芯片市场有何影响」，
  LLM 的 messages 里却出现了两条连续的「总结核心内容」HumanMessage。

根因链路：
  1) 文章生成路径 _stream_kb_article 用知识库名（如「半导体」）作会话标题
     （server/api/knowledge.py:709），而前端 ensureConv 用 title !== '生成文章'
     过滤生成会话（web/src/pages/KnowledgeBaseView.vue:288）——两端约定不一致。
  2) 于是聊天面板误选了 gen_{kb_id} 这个文章生成会话作为 currentConvId。
  3) 文章生成路径此前在该 conv_id 下存了多条「总结核心内容」user 消息（连续，
     中间无 AI——生成被中断时 user 已存、AI 未存）。
  4) 聊天首次用该 conv_id 时，migrate_history（api/knowledge.py:909）把这些
     旧 user 消息迁进 graph state。
  5) generate 节点（core/rag_graph.py:459）把 compressed_messages + [HumanMessage(query)]
     全发给 LLM → 历史里的重复 Human 加上本次 query，LLM 收到多条 User。

本测试聚焦后端可独立验证的部分：generate 节点对「历史含连续 Human + 本次不同 query」
的处理，以及 migrate_history 的转换。前端会话串台需集成测试，此处用注释说明。
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import core.rag_graph as rag_mod


class _FakeLLM:
    """记录 generate 节点传给 LLM 的消息，并返回固定流式内容。"""

    def __init__(self, *, capture_key: str, sink: dict[str, Any], reply: str = "AI 回复"):
        self._capture_key = capture_key
        self._sink = sink
        self._reply = reply

    async def astream(self, messages, **kwargs):
        # 记录本次调用实际收到的消息列表
        self._sink.setdefault(self._capture_key, []).append(list(messages))
        # 模拟流式输出：分两 chunk 返回
        yield _Chunk(self._reply[:3])
        yield _Chunk(self._reply[3:])

    async def ainvoke(self, messages, **kwargs):
        # generate 节点不调用 ainvoke；summary middleware 会调用，但本测试不触发摘要
        return AIMessage(content="摘要")


class _Chunk:
    """模拟 LangChain stream chunk，只暴露 content 属性。"""

    def __init__(self, content: str) -> None:
        self.content = content


def _human_contents(messages: list) -> list[str]:
    """从消息列表中提取所有 HumanMessage 的 content。"""
    return [m.content for m in messages if isinstance(m, HumanMessage)]


@pytest.fixture()
def isolated_rag_checkpointer(monkeypatch, tmp_path):
    """每个测试用独立的 rag_memory.db，避免跨测试污染 checkpointer 状态。"""
    monkeypatch.setattr(rag_mod, "KB_RAG_MEMORY_DB_PATH", str(tmp_path / "rag_memory.db"))
    # 重置单例 compiled graph，强制下一轮 get_rag_graph 重新编译
    monkeypatch.setattr(rag_mod, "_compiled_rag_graph", None)
    monkeypatch.setattr(rag_mod, "_rag_checkpointer", None)
    monkeypatch.setattr(rag_mod, "_rag_checkpointer_ctx", None)
    yield


async def _run_generate(state: dict) -> dict:
    """直接调用 generate 节点（绕过 graph 调度），返回其返回值。"""
    return await rag_mod.generate(state)


@pytest.mark.asyncio
async def test_generate_keeps_consecutive_human_messages(monkeypatch):
    """generate 节点如实转发历史消息，保留连续 HumanMessage 的真实形态。

    文章生成路径遗留的连续 HumanMessage 应由 migrate_history 过滤（type='article'），
    不应到达聊天上下文；此测试验证：当历史确实以连续 Human 结尾时，generate 不会
    合并或丢弃，而是原样交给 LLM，便于观测和分析真实消息序列。
    """
    captured: dict[str, Any] = {}

    def fake_chat_openai(**kwargs):
        return _FakeLLM(capture_key="llm_messages", sink=captured, reply="AI 回复")

    monkeypatch.setattr(rag_mod, "ChatOpenAI", fake_chat_openai)

    history = [
        HumanMessage(content="总结核心内容"),
        HumanMessage(content="总结核心内容"),
    ]
    state = {
        "messages": history,
        "query": "英伟达Rubin的量产交付对AI芯片市场有何影响",
        "context": "知识库片段内容……",
        "intent": "summary",
        "doc_meta": "",
        "web_context": "",
    }

    await _run_generate(state)

    assert captured["llm_messages"], "generate 未调用 LLM"
    llm_msgs = captured["llm_messages"][0]
    humans = _human_contents(llm_msgs)
    # 保留真实场景：历史里的 2 条「总结核心内容」+ 本次 query 都传给 LLM
    assert humans.count("总结核心内容") == 2, f"期望历史遗留 2 条「总结核心内容」，实际 {humans!r}"
    assert "英伟达Rubin的量产交付对AI芯片市场有何影响" in humans


@pytest.mark.asyncio
async def test_generate_single_human_when_no_history(monkeypatch):
    """对照测试：无历史时，generate 只给 LLM 发 1 条 User 消息（本次 query）。"""
    captured: dict[str, Any] = {}

    def fake_chat_openai(**kwargs):
        return _FakeLLM(capture_key="llm_messages", sink=captured)

    monkeypatch.setattr(rag_mod, "ChatOpenAI", fake_chat_openai)

    state = {
        "messages": [],
        "query": "英伟达Rubin的量产交付对AI芯片市场有何影响",
        "context": "知识库片段内容……",
        "intent": "summary",
        "doc_meta": "",
        "web_context": "",
    }

    await _run_generate(state)

    llm_msgs = captured["llm_messages"][0]
    humans = _human_contents(llm_msgs)
    assert humans == ["英伟达Rubin的量产交付对AI芯片市场有何影响"]


@pytest.mark.asyncio
async def test_generate_writes_back_query_and_ai_to_state(isolated_rag_checkpointer, monkeypatch):
    """验证 generate 的 return 值会经 _add_messages 追加进 state。
    这是历史累积机制——每轮 query 都会被持久化，下一轮成为历史。"""
    monkeypatch.setattr(rag_mod, "ChatOpenAI", lambda **k: _FakeLLM(capture_key="x", sink={}))

    state = {
        "messages": [],
        "query": "总结核心内容",
        "context": "片段",
        "intent": "summary",
        "doc_meta": "",
        "web_context": "",
    }

    result = await _run_generate(state)

    # generate return 的是 [HumanMessage(query), AIMessage(content)]
    assert isinstance(result["messages"], list)
    assert len(result["messages"]) == 2
    assert isinstance(result["messages"][0], HumanMessage)
    assert result["messages"][0].content == "总结核心内容"
    assert isinstance(result["messages"][1], AIMessage)

    # _add_messages reducer 把 return 追加到现有 messages，正是历史累积机制
    existing = [HumanMessage(content="上一轮")]
    merged = rag_mod._add_messages(existing, result["messages"])
    assert len(merged) == 3
    assert merged[0].content == "上一轮"
    assert merged[1].content == "总结核心内容"  # 历史里多出一条本轮 query


@pytest.mark.asyncio
async def test_migrate_history_filters_article_messages(monkeypatch, tmp_path):
    """回归测试：migrate_history 只加载 type='chat' 的消息。

    文章生成路径（type='article'）使用独立会话命名空间，其中断遗留的 user/assistant
    记录不应被迁进 RAG 问答上下文，避免 LLM 收到重复或未配对的 User 消息。
    """
    fake_old_msgs = [
        {"role": "user", "content": "聊天问题 1", "type": "chat"},
        {"role": "assistant", "content": "聊天回答 1", "type": "chat"},
        {"role": "user", "content": "总结核心内容", "type": "article"},
        {"role": "user", "content": "总结核心内容", "type": "article"},
    ]
    monkeypatch.setattr("database.load_messages", lambda conv_id: _async_iter(fake_old_msgs))

    result = await rag_mod.migrate_history("gen_test_kb")

    assert len(result) == 2
    assert isinstance(result[0], HumanMessage) and result[0].content == "聊天问题 1"
    assert isinstance(result[1], AIMessage) and result[1].content == "聊天回答 1"
    # article 类型消息已被过滤掉
    assert all(m.content != "总结核心内容" for m in result)


async def _async_iter(items):
    """让 mock 的 load_messages 兼容 await（真实函数是 async）。"""
    return items
