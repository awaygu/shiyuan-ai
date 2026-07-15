"""DashScopeEmbedding 测试：限流逻辑 + embed/embed_query 路径（mock DashScope API）。

不真实调用 DashScope，mock TextEmbedding.call 返回固定 embedding。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rag import embeddings as emb_mod
from rag.embeddings import BATCH_SIZE, RATE_LIMIT_CALLS, DashScopeEmbedding


class _FakeResp:
    def __init__(self, embeddings: list[list[float]], status_code: int = 200):
        self.status_code = status_code
        self.message = ""
        self.output = {"embeddings": [{"embedding": e} for e in embeddings]}


def test_embed_empty_returns_empty():
    """空输入直接返回空列表，不调用 API。"""
    embs = DashScopeEmbedding().embed([])
    assert embs == []


def test_embed_single_query():
    """单条文本返回单条 embedding。"""
    emb = DashScopeEmbedding(api_key="dummy")
    with patch.object(emb_mod.TextEmbedding, "call", return_value=_FakeResp([[0.1, 0.2, 0.3]])) as mock_call:
        result = emb.embed(["hello"])
    assert result == [[0.1, 0.2, 0.3]]
    mock_call.assert_called_once()


def test_embed_batches_by_batch_size():
    """超过 BATCH_SIZE 的输入分批调用 API。"""
    emb = DashScopeEmbedding(api_key="dummy")
    # 每条返回 2 维向量
    vectors = [[float(i), float(i + 1)] for i in range(BATCH_SIZE + 3)]
    with patch.object(
        emb_mod.TextEmbedding,
        "call",
        side_effect=[_FakeResp(vectors[:BATCH_SIZE]), _FakeResp(vectors[BATCH_SIZE:])],
    ) as mock_call:
        result = emb.embed([f"text{i}" for i in range(BATCH_SIZE + 3)])
    assert len(result) == BATCH_SIZE + 3
    assert mock_call.call_count == 2


def test_embed_api_failure_raises_runtime_error():
    """API 返回非 200 抛 RuntimeError。"""
    emb = DashScopeEmbedding(api_key="dummy")
    bad = _FakeResp([], status_code=500)
    bad.message = "quota exceeded"
    with (
        patch.object(emb_mod.TextEmbedding, "call", return_value=bad),
        pytest.raises(RuntimeError, match="DashScope embedding failed"),
    ):
        emb.embed(["x"])


def test_embed_query_returns_first_vector():
    """embed_query 返回 embed 结果的第一条。"""
    emb = DashScopeEmbedding(api_key="dummy")
    with patch.object(emb_mod.TextEmbedding, "call", return_value=_FakeResp([[0.5, 0.6]])):
        result = emb.embed_query("query")
    assert result == [0.5, 0.6]


def test_rate_limit_wait_sleeps_when_limit_reached():
    """超过 RATE_LIMIT_CALLS 时 _rate_limit_wait 会 sleep。"""
    emb = DashScopeEmbedding(api_key="dummy")
    # 预填时间戳使下一调用触发限流
    import time

    now = time.monotonic()
    emb._call_timestamps = [now - 0.01 for _ in range(RATE_LIMIT_CALLS)]
    with patch.object(emb_mod.time, "sleep") as mock_sleep:
        emb._rate_limit_wait()
    # 应至少 sleep 一次（等待窗口过去）
    assert mock_sleep.called


def test_rate_limit_appends_timestamp():
    """_rate_limit_wait 总会追加当前时间戳。"""
    emb = DashScopeEmbedding(api_key="dummy")
    with patch.object(emb_mod.time, "sleep"):
        emb._rate_limit_wait()
    assert len(emb._call_timestamps) == 1


async def test_embed_async_delegates_to_embed():
    """embed_async 通过线程池调用同步 embed。"""
    emb = DashScopeEmbedding(api_key="dummy")
    with patch.object(emb_mod.TextEmbedding, "call", return_value=_FakeResp([[0.1, 0.2]])):
        result = await emb.embed_async(["hello"])
    assert result == [[0.1, 0.2]]


async def test_embed_query_async_returns_vector():
    emb = DashScopeEmbedding(api_key="dummy")
    with patch.object(emb_mod.TextEmbedding, "call", return_value=_FakeResp([[0.7, 0.8]])):
        result = await emb.embed_query_async("q")
    assert result == [0.7, 0.8]
