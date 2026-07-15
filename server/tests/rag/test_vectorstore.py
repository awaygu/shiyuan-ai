"""FAISSVectorStore 增删查测试（真实 FAISS + numpy，离线，独立 UPLOAD_DIR）。

用低维向量（dim=4）便于断言，验证 add/search/remove_by_doc/total_vectors、
doc_ids 过滤、空库与持久化（save 后重新 load）。

注意：FAISS 的 swig write_index 在 Windows 下对含非 ASCII 字符的路径
（如用户名"古"的 temp 目录）会失败，故使用项目目录（全 ASCII）下的
临时上传目录，测试后清理。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rag.vectorstore import FAISSVectorStore, VectorStoreManager

# 项目 server 目录是全 ASCII 路径，faiss 在此可正常读写
_SERVER_DIR = Path(__file__).resolve().parent.parent
_TEST_UPLOAD = _SERVER_DIR / "_test_uploads_vectorstore"


@pytest.fixture(autouse=True)
def _isolated_upload_dir(monkeypatch):
    """每个测试会话用独立 UPLOAD_DIR（ASCII 路径），结束后清理。"""
    _TEST_UPLOAD.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("rag.vectorstore.UPLOAD_DIR", str(_TEST_UPLOAD))
    monkeypatch.setattr("config.UPLOAD_DIR", str(_TEST_UPLOAD))
    yield _TEST_UPLOAD
    # 每个测试后清空内容，避免互相影响
    if _TEST_UPLOAD.exists():
        shutil.rmtree(_TEST_UPLOAD, ignore_errors=True)


def _vec(seed: float) -> list[float]:
    """生成 4 维单位向量（便于点积/排序断言）。"""
    import math

    v = [seed, 1.0 - seed, seed * 0.5, 0.3]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def test_vectorstore_add_and_search_returns_matching_ids(_isolated_upload_dir):
    store = FAISSVectorStore(dim=4, kb_id="kb-add")
    store.add(["c1", "c2"], [_vec(0.1), _vec(0.9)], doc_id="d1")
    assert store.total_vectors == 2

    results = store.search(_vec(0.9), top_k=2)
    assert len(results) == 2
    ids = [r[0] for r in results]
    assert "c1" in ids and "c2" in ids
    # 与 _vec(0.9) 更近的 c2 应得分更高
    scores = dict(results)
    assert scores["c2"] >= scores["c1"]


def test_vectorstore_search_empty_returns_empty(_isolated_upload_dir):
    store = FAISSVectorStore(dim=4, kb_id="kb-empty")
    assert store.search(_vec(0.5), top_k=5) == []


def test_vectorstore_search_with_doc_ids_filter(_isolated_upload_dir):
    store = FAISSVectorStore(dim=4, kb_id="kb-filter")
    store.add(["c1", "c2", "c3"], [_vec(0.1), _vec(0.2), _vec(0.3)], doc_id="d1")
    store.add(["c4"], [_vec(0.4)], doc_id="d2")
    results = store.search(_vec(0.2), top_k=5, doc_ids=["d1"])
    ids = {r[0] for r in results}
    assert ids == {"c1", "c2", "c3"}
    assert "c4" not in ids


def test_vectorstore_search_empty_doc_ids_returns_empty(_isolated_upload_dir):
    """doc_ids=[] 显式空列表返回空（FAISSVectorStore 语义，与 BM25Index 不同）。"""
    store = FAISSVectorStore(dim=4, kb_id="kb-empty-filter")
    store.add(["c1"], [_vec(0.1)], doc_id="d1")
    assert store.search(_vec(0.1), top_k=5, doc_ids=[]) == []


def test_vectorstore_search_nonexistent_doc_ids_returns_empty(_isolated_upload_dir):
    store = FAISSVectorStore(dim=4, kb_id="kb-nodoc")
    store.add(["c1"], [_vec(0.1)], doc_id="d1")
    assert store.search(_vec(0.1), top_k=5, doc_ids=["nope"]) == []


def test_vectorstore_remove_by_doc_partial(_isolated_upload_dir):
    """remove_by_doc 删除指定 chunk_id，保留其余，索引可继续搜索。"""
    store = FAISSVectorStore(dim=4, kb_id="kb-rm")
    store.add(["c1", "c2"], [_vec(0.1), _vec(0.2)], doc_id="d1")
    store.add(["c3"], [_vec(0.3)], doc_id="d2")
    store.remove_by_doc({"c1"})
    assert store.total_vectors == 2
    results = store.search(_vec(0.3), top_k=5)
    ids = {r[0] for r in results}
    assert ids == {"c2", "c3"}
    assert "c1" not in ids


def test_vectorstore_remove_by_doc_all_rebuilds_empty(_isolated_upload_dir):
    """删除全部 chunk 后索引重建为空。"""
    store = FAISSVectorStore(dim=4, kb_id="kb-rm-all")
    store.add(["c1", "c2"], [_vec(0.1), _vec(0.2)], doc_id="d1")
    store.remove_by_doc({"c1", "c2"})
    assert store.total_vectors == 0
    assert store.search(_vec(0.1), top_k=5) == []


def test_vectorstore_persists_and_reloads(_isolated_upload_dir):
    """save 后新建 store 实例从磁盘加载已有索引。"""
    store = FAISSVectorStore(dim=4, kb_id="kb-persist")
    store.add(["c1"], [_vec(0.1)], doc_id="d1")
    assert (Path(_isolated_upload_dir) / "kb-persist" / "kb_index.faiss").exists()
    assert (Path(_isolated_upload_dir) / "kb-persist" / "kb_id_map.json").exists()

    # 新实例从磁盘加载
    store2 = FAISSVectorStore(dim=4, kb_id="kb-persist")
    assert store2.total_vectors == 1
    results = store2.search(_vec(0.1), top_k=5)
    assert results[0][0] == "c1"


def test_vectorstore_manager_get_caches(_isolated_upload_dir):
    mgr = VectorStoreManager(dim=4)
    s1 = mgr.get("mgr-kb1")
    s2 = mgr.get("mgr-kb1")
    assert s1 is s2


def test_vectorstore_manager_remove_deletes_store_and_files(_isolated_upload_dir):
    mgr = VectorStoreManager(dim=4)
    store = mgr.get("mgr-kb-rm")
    store.add(["c1"], [_vec(0.1)], doc_id="d1")
    kb_dir = Path(_isolated_upload_dir) / "mgr-kb-rm"
    assert (kb_dir / "kb_index.faiss").exists()

    mgr.remove("mgr-kb-rm")
    assert "mgr-kb-rm" not in mgr._stores
    # 磁盘文件已删除
    assert not (kb_dir / "kb_index.faiss").exists()
    assert not (kb_dir / "kb_id_map.json").exists()


async def test_vectorstore_manager_add_async_and_remove_async(_isolated_upload_dir, monkeypatch):
    """VectorStoreManager.add_async / remove_by_doc_async 异步路径 + BM25 联动。

    add_async / remove_by_doc_async 会调用 BM25 索引的 add_chunks /
    remove_chunks（触发惰性重建，依赖 DB）。这里用 stub 替换 BM25 manager，
    只验证向量增删不报错、total_vectors 正确。
    """

    class _StubBM25Idx:
        async def add_chunks(self, chunks):
            return None

        async def remove_chunks(self, chunk_ids):
            return None

    class _StubBM25Mgr:
        def get(self, kb_id):
            return _StubBM25Idx()

        def remove(self, kb_id):
            return None

    mgr = VectorStoreManager(dim=4)
    monkeypatch.setattr(mgr, "_get_bm25", lambda: _StubBM25Mgr())

    await mgr.add_async("async-kb", ["c1", "c2"], [_vec(0.1), _vec(0.2)], doc_id="d1")
    assert mgr.get("async-kb").total_vectors == 2

    await mgr.remove_by_doc_async("async-kb", {"c1"})
    assert mgr.get("async-kb").total_vectors == 1
