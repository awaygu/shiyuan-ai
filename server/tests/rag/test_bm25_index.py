"""BM25 索引构建/搜索/增删基础测试（真实 jieba + rank_bm25，离线）。

不 mock 分词器与 BM25 实现，验证 BM25Index 的 lazy 构建、search 排序、
doc_ids 过滤、add_chunks/remove_chunks 重建逻辑。
"""

from __future__ import annotations

import pytest

import database as db
from rag.bm25_index import BM25Index, BM25IndexManager


@pytest.fixture(autouse=True)
async def _fresh_db(monkeypatch, tmp_path):
    """每个测试独立 DB + 预置 kb_documents/kb_chunks 数据。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai.db")
    await db.close_db()
    monkeypatch.setattr(db, "_db", None)
    await db.init_db()
    yield
    await db.close_db()


async def _seed_chunks(kb_id: str, chunks: list[dict]) -> None:
    """直接向 kb_documents / kb_chunks 插入 chunk 记录供 BM25 构建。"""
    conn = await db.get_db()
    # 先建一个 kb 记录（避免外键约束问题，knowledge_bases 表可选）
    for ch in chunks:
        # 确保 doc 存在
        await conn.execute(
            "INSERT OR IGNORE INTO kb_documents (doc_id, kb_id, filename) VALUES (?, ?, ?)",
            (ch["doc_id"], kb_id, ch.get("filename", ch["doc_id"])),
        )
        await conn.execute(
            "INSERT INTO kb_chunks (chunk_id, doc_id, chunk_index, page, text) VALUES (?, ?, ?, ?, ?)",
            (ch["chunk_id"], ch["doc_id"], ch.get("chunk_index", 0), ch.get("page", 0), ch["text"]),
        )
    await conn.commit()


async def test_bm25_build_empty_kb_returns_false():
    """无 chunk 的 KB，_ensure_built 返回 False，search 返回空。"""
    idx = BM25Index("empty-kb")
    built = await idx._ensure_built()
    assert built is False
    assert await idx.search("任意查询") == []


async def test_bm25_search_ranks_relevant_chunk_higher():
    """有 chunk 时，包含查询关键词的 chunk 排名靠前。"""
    await _seed_chunks(
        "kb1",
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "人工智能芯片市场迎来重大技术突破"},
            {"chunk_id": "c2", "doc_id": "d1", "text": "今天天气晴朗适合户外运动"},
            {"chunk_id": "c3", "doc_id": "d2", "text": "半导体产业的人工智能需求持续增长"},
        ],
    )
    idx = BM25Index("kb1")
    results = await idx.search("人工智能", top_k=3)
    assert len(results) > 0
    ids = [r[0] for r in results]
    # 两个含"人工智能"的 chunk 应排在最前
    assert "c1" in ids
    assert "c3" in ids
    # c2（天气）不应高于含关键词的 chunk
    assert ids.index("c2") > ids.index("c1") or "c2" not in ids
    # 分数为 float
    assert all(isinstance(s, float) for _, s in results)


async def test_bm25_search_top_k_limits_results():
    """top_k 限制返回条数。"""
    await _seed_chunks(
        "kb2",
        [{"chunk_id": f"c{i}", "doc_id": "d1", "text": f"关键词 测试 编号{i}"} for i in range(5)],
    )
    idx = BM25Index("kb2")
    results = await idx.search("关键词", top_k=2)
    assert len(results) <= 2


async def test_bm25_search_no_query_tokens_returns_empty():
    """查询分词后无有效 token（纯标点/单字）返回空。"""
    await _seed_chunks("kb3", [{"chunk_id": "c1", "doc_id": "d1", "text": "正常文本内容"}])
    idx = BM25Index("kb3")
    # 纯标点和数字，分词后应被过滤
    assert await idx.search("。。123") == []


async def test_bm25_search_with_doc_ids_filter():
    """指定 doc_ids 时只返回属于这些文档的 chunk。"""
    await _seed_chunks(
        "kb4",
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "人工智能芯片技术"},
            {"chunk_id": "c2", "doc_id": "d2", "text": "人工智能应用场景"},
            {"chunk_id": "c3", "doc_id": "d3", "text": "人工智能未来展望"},
        ],
    )
    idx = BM25Index("kb4")
    # 只在 d1/d3 范围内搜
    results = await idx.search("人工智能", top_k=5, doc_ids=["d1", "d3"])
    ids = {r[0] for r in results}
    assert ids == {"c1", "c3"}
    assert "c2" not in ids


async def test_bm25_search_with_nonexistent_doc_ids_returns_empty():
    """doc_ids 全部不存在时返回空。"""
    await _seed_chunks("kb5", [{"chunk_id": "c1", "doc_id": "d1", "text": "人工智能"}])
    idx = BM25Index("kb5")
    assert await idx.search("人工智能", doc_ids=["nope"]) == []


async def test_bm25_search_empty_doc_ids_treated_as_none():
    """doc_ids=[] 空列表在 BM25Index 中被视为不过滤（与 None 等价）。

    注意：这与 FAISSVectorStore.search 的语义不同（后者对 len==0 返回空）。
    BM25Index.search 的判断是 `doc_ids is not None and len(doc_ids) > 0`，
    空列表不进入过滤分支，返回全部命中。此处锁定该行为以便后续变更可察觉。
    """
    await _seed_chunks("kb6", [{"chunk_id": "c1", "doc_id": "d1", "text": "人工智能芯片"}])
    idx = BM25Index("kb6")
    results = await idx.search("人工智能", doc_ids=[])
    # 空列表不过滤，返回全部命中
    assert any(r[0] == "c1" for r in results)


async def test_bm25_add_chunks_rebuilds_index():
    """add_chunks 后索引重建，新 chunk 可被搜到。"""
    await _seed_chunks("kb7", [{"chunk_id": "c1", "doc_id": "d1", "text": "人工智能芯片"}])
    idx = BM25Index("kb7")
    await idx.search("人工智能")  # 触发构建

    # 新增 chunk（直接写 DB 后调 add_chunks 触发重建）
    await _seed_chunks("kb7", [{"chunk_id": "c2", "doc_id": "d1", "text": "区块链应用"}])
    await idx.add_chunks([])
    results = await idx.search("区块链")
    assert any(r[0] == "c2" for r in results)


async def test_bm25_remove_chunks_rebuilds_index():
    """remove_chunks 后被删 chunk 不再可搜。"""
    await _seed_chunks(
        "kb8",
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "人工智能芯片"},
            {"chunk_id": "c2", "doc_id": "d1", "text": "区块链应用"},
        ],
    )
    idx = BM25Index("kb8")
    await idx.search("人工智能")  # 构建索引

    # 从 DB 删除 c2 后调 remove_chunks 触发重建
    conn = await db.get_db()
    await conn.execute("DELETE FROM kb_chunks WHERE chunk_id = ?", ("c2",))
    await conn.commit()
    await idx.remove_chunks({"c2"})
    results = await idx.search("区块链")
    assert all(r[0] != "c2" for r in results)


def test_bm25_index_manager_get_and_remove():
    """BM25IndexManager.get 创建并缓存索引，remove 移除。"""
    mgr = BM25IndexManager()
    idx1 = mgr.get("mgr-kb1")
    idx2 = mgr.get("mgr-kb1")
    assert idx1 is idx2  # 同一 kb 返回同一实例
    idx3 = mgr.get("mgr-kb2")
    assert idx3 is not idx1
    mgr.remove("mgr-kb1")
    idx4 = mgr.get("mgr-kb1")
    assert idx4 is not idx1  # remove 后是新建实例
