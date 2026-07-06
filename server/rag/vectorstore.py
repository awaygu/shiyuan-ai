"""FAISS + SQLite vector store for knowledge base chunks."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import numpy as np

from config import KB_EMBEDDING_DIM, UPLOAD_DIR

logger = logging.getLogger(__name__)


class FAISSVectorStore:
    def __init__(self, dim: int = 0, kb_id: str = "default"):
        self.dim = dim or KB_EMBEDDING_DIM
        self.kb_id = kb_id
        self.index = None
        self.id_map: list[str] = []
        self.chunk_doc_map: dict[str, str] = {}
        self._loaded = False
        self._vectors: list = []

        kb_dir = Path(UPLOAD_DIR) / kb_id
        kb_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = kb_dir / "kb_index.faiss"
        self._idmap_path = kb_dir / "kb_id_map.json"
        self._chunk_doc_path = kb_dir / "kb_chunk_doc_map.json"

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            import faiss

            if self._index_path.exists() and self._idmap_path.exists():
                self.index = faiss.read_index(str(self._index_path))
                self.id_map = json.loads(self._idmap_path.read_text("utf-8"))
                logger.info("Loaded FAISS index for KB %s: %d vectors", self.kb_id, self.index.ntotal)
            else:
                self.index = faiss.IndexFlatIP(self.dim)
                self.id_map = []
                logger.info("Created empty FAISS index for KB %s (dim=%d)", self.kb_id, self.dim)
        except ImportError:
            logger.warning("faiss not installed, using brute-force search")
            self.index = None
            self._vectors = []
            self.id_map = []

        if self._chunk_doc_path.exists():
            self.chunk_doc_map = json.loads(self._chunk_doc_path.read_text("utf-8"))
        else:
            self.chunk_doc_map = {}

    def save(self):
        if self.index is not None:
            import faiss

            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self.index, str(self._index_path))
        self._idmap_path.parent.mkdir(parents=True, exist_ok=True)
        self._idmap_path.write_text(json.dumps(self.id_map, ensure_ascii=False), encoding="utf-8")
        self._chunk_doc_path.write_text(json.dumps(self.chunk_doc_map, ensure_ascii=False), encoding="utf-8")

    def add(self, chunk_ids: list[str], vectors: list[list[float]], doc_id: str = ""):
        self._ensure_loaded()
        vecs = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        vecs = vecs / norms

        if self.index is not None:
            self.index.add(vecs)
        else:
            self._vectors.extend(vecs)

        self.id_map.extend(chunk_ids)
        if doc_id:
            for cid in chunk_ids:
                self.chunk_doc_map[cid] = doc_id
        self.save()

    def search(
        self, query_vector: list[float], top_k: int = 10, doc_ids: list[str] | None = None
    ) -> list[tuple[str, float]]:
        self._ensure_loaded()
        q = np.array([query_vector], dtype=np.float32)
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        if doc_ids is not None and len(doc_ids) == 0:
            return []

        if doc_ids is not None:
            target_doc_set = set(doc_ids)
            target_indices = [i for i, cid in enumerate(self.id_map) if self.chunk_doc_map.get(cid) in target_doc_set]
            if not target_indices:
                return []

            if self.index is not None and self.index.ntotal > 0:
                all_vecs = self.index.reconstruct_n(0, self.index.ntotal)
                subset_vecs = np.array([all_vecs[i] for i in target_indices], dtype=np.float32)
            else:
                all_vecs = (
                    np.array(self._vectors, dtype=np.float32)
                    if hasattr(self, "_vectors")
                    else np.array([], dtype=np.float32)
                )
                if len(all_vecs) == 0:
                    return []
                subset_vecs = all_vecs[target_indices]

            if len(subset_vecs) == 0:
                return []
            scores = np.dot(subset_vecs, q[0])
            actual_k = min(top_k, len(target_indices))
            top_local = np.argsort(scores)[::-1][:actual_k]
            return [(self.id_map[target_indices[i]], float(scores[i])) for i in top_local]

        if self.index is not None and self.index.ntotal > 0:
            actual_k = min(top_k, self.index.ntotal)
            scores, ids = self.index.search(q, actual_k)
            results = []
            for score, idx in zip(scores[0], ids[0]):
                if idx < len(self.id_map):
                    results.append((self.id_map[idx], float(score)))
            return results
        else:
            all_vecs = (
                np.array(self._vectors, dtype=np.float32)
                if hasattr(self, "_vectors")
                else np.array([], dtype=np.float32)
            )
            if len(all_vecs) == 0:
                return []
            scores = np.dot(all_vecs, q[0])
            top_indices = np.argsort(scores)[::-1][:top_k]
            return [(self.id_map[i], float(scores[i])) for i in top_indices]

    def remove_by_doc(self, chunk_ids: set[str]):
        self._ensure_loaded()
        keep_indices = [i for i, cid in enumerate(self.id_map) if cid not in chunk_ids]
        if not keep_indices:
            self._rebuild_empty()
            return

        if self.index is not None:
            import faiss

            keep_vecs = self.index.reconstruct_n(0, self.index.ntotal)
            keep_vecs = np.array([keep_vecs[i] for i in keep_indices], dtype=np.float32)
            self.id_map = [self.id_map[i] for i in keep_indices]
            self.index = faiss.IndexFlatIP(self.dim)
            if len(keep_vecs) > 0:
                self.index.add(keep_vecs)
        else:
            self._vectors = [self._vectors[i] for i in keep_indices]
            self.id_map = [self.id_map[i] for i in keep_indices]
        for cid in chunk_ids:
            self.chunk_doc_map.pop(cid, None)
        self.save()

    def _rebuild_empty(self):
        if self.index is not None:
            import faiss

            self.index = faiss.IndexFlatIP(self.dim)
        else:
            self._vectors = []
        self.id_map = []
        self.chunk_doc_map = {}
        self.save()

    @property
    def total_vectors(self) -> int:
        self._ensure_loaded()
        if self.index is not None:
            return self.index.ntotal
        return len(self.id_map)


class VectorStoreManager:
    def __init__(self, dim: int = 0):
        self.dim = dim or KB_EMBEDDING_DIM
        self._stores: dict[str, FAISSVectorStore] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._bm25_manager = None

    def _get_bm25(self):
        """Lazy init BM25 manager to avoid circular imports at module level."""
        if self._bm25_manager is None:
            from rag.bm25_index import BM25IndexManager

            self._bm25_manager = BM25IndexManager()
        return self._bm25_manager

    def _get_lock(self, kb_id: str) -> asyncio.Lock:
        if kb_id not in self._locks:
            self._locks[kb_id] = asyncio.Lock()
        return self._locks[kb_id]

    def get(self, kb_id: str) -> FAISSVectorStore:
        if kb_id not in self._stores:
            self._stores[kb_id] = FAISSVectorStore(dim=self.dim, kb_id=kb_id)
        return self._stores[kb_id]

    async def add_async(self, kb_id: str, chunk_ids: list[str], vectors: list[list[float]], doc_id: str = ""):
        async with self._get_lock(kb_id):
            store = self.get(kb_id)
            await asyncio.to_thread(store.add, chunk_ids, vectors, doc_id)
            # 重建 BM25 索引（下次检索时 lazy rebuild）
            bm25 = self._get_bm25().get(kb_id)
            await bm25.add_chunks([])

    async def remove_by_doc_async(self, kb_id: str, chunk_ids: set[str]):
        async with self._get_lock(kb_id):
            store = self.get(kb_id)
            await asyncio.to_thread(store.remove_by_doc, chunk_ids)
            # 重建 BM25 索引
            bm25 = self._get_bm25().get(kb_id)
            await bm25.remove_chunks(chunk_ids)

    def remove(self, kb_id: str):
        if kb_id in self._stores:
            del self._stores[kb_id]
        self._locks.pop(kb_id, None)
        # 清理 BM25 索引
        if self._bm25_manager is not None:
            self._bm25_manager.remove(kb_id)
        kb_dir = Path(UPLOAD_DIR) / kb_id
        if kb_dir.exists():
            for f in kb_dir.glob("kb_index.faiss"):
                f.unlink(missing_ok=True)
            for f in kb_dir.glob("kb_id_map.json"):
                f.unlink(missing_ok=True)
            for f in kb_dir.glob("kb_chunk_doc_map.json"):
                f.unlink(missing_ok=True)
