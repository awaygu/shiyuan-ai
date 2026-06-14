"""BM25 keyword search index for knowledge base chunks.

Lazy-built from DB on first use.  Chinese text is tokenised with jieba.
"""

from __future__ import annotations

import asyncio
import json
import logging
import string
from pathlib import Path
from typing import Any

from config import UPLOAD_DIR

logger = logging.getLogger(__name__)

# ── Tokenization ─────────────────────────────────────────────────

# 中文常用停用词表（可扩展或从文件加载）
_STOPWORDS: set[str] = set()


def _tokenize(text: str) -> list[str]:
    """jieba 分词，过滤停用词、单字、纯数字、纯标点。"""
    import jieba

    tokens = list(jieba.cut(text.strip(), cut_all=False))
    return [
        t for t in tokens
        if len(t) > 1                               # 过滤单字（中文单字区分度低）
        and not t.isdigit()                         # 过滤纯数字
        and not all(c in string.punctuation for c in t)  # 过滤纯标点
        and t not in _STOPWORDS                     # 过滤停用词
    ]


# ── BM25 Index ───────────────────────────────────────────────────


class BM25Index:
    """Per-kb BM25 index.  Built lazily from DB, kept in memory."""

    def __init__(self, kb_id: str):
        self.kb_id = kb_id
        self._bm25: Any = None
        self._chunk_ids: list[str] = []
        self._tokens_list: list[list[str]] = []
        self._chunk_doc_map: dict[str, str] = {}  # chunk_id → doc_id, built once from DB
        self._built = False
        self._build_lock = asyncio.Lock()

    async def _ensure_built(self) -> bool:
        """从数据库加载所有 chunk 文本并构建 BM25 索引。

        Returns False if no chunks available.
        """
        if self._built:
            return True

        async with self._build_lock:
            if self._built:
                return True

            from database import load_kb_all_chunks

            try:
                chunks = await load_kb_all_chunks(self.kb_id)
            except Exception as e:
                logger.warning("BM25 build failed to load chunks for KB %s: %s", self.kb_id, e)
                return False

            if not chunks:
                logger.info("BM25: no chunks for KB %s", self.kb_id)
                self._built = True
                return False

            self._chunk_ids = [c["chunk_id"] for c in chunks]
            self._tokens_list = [_tokenize(c["text"]) for c in chunks]
            self._chunk_doc_map = {c["chunk_id"]: c.get("doc_id", "") for c in chunks}

            try:
                from rank_bm25 import BM25Okapi

                self._bm25 = BM25Okapi(self._tokens_list)
            except ImportError:
                logger.error("rank-bm25 not installed, BM25 search unavailable")
                self._built = True
                return False

            self._built = True
            logger.info(
                "BM25 index built for KB %s: %d chunks, avg %d tokens/chunk",
                self.kb_id,
                len(self._chunk_ids),
                sum(len(t) for t in self._tokens_list) // max(len(self._tokens_list), 1),
            )
            return True

    async def search(
        self, query: str, top_k: int = 20, doc_ids: list[str] | None = None
    ) -> list[tuple[str, float]]:
        """BM25 keyword search.  Returns (chunk_id, score) sorted by score desc."""
        if not await self._ensure_built():
            return []

        if not self._bm25:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scores = self._bm25.get_scores(query_tokens)

        # 如果指定了 doc_ids，过滤掉不属于这些文档的 chunk
        if doc_ids is not None and len(doc_ids) > 0:
            valid_indices = [
                i for i, cid in enumerate(self._chunk_ids)
                if self._chunk_doc_map.get(cid) in doc_ids
            ]
            if not valid_indices:
                return []
            filtered = [(self._chunk_ids[i], float(scores[i])) for i in valid_indices]
        else:
            filtered = [
                (cid, float(scores[i]))
                for i, cid in enumerate(self._chunk_ids)
            ]

        filtered.sort(key=lambda x: x[1], reverse=True)
        return filtered[:top_k]

    async def add_chunks(self, chunks: list[dict[str, Any]]) -> None:
        """添加新 chunk，重建索引。"""
        # 简单方案：重建
        self._built = False
        self._bm25 = None
        self._chunk_ids = []
        self._tokens_list = []
        self._chunk_doc_map = {}
        await self._ensure_built()

    async def remove_chunks(self, chunk_ids: set[str]) -> None:
        """删除 chunk，重建索引。"""
        self._built = False
        self._bm25 = None
        self._chunk_ids = []
        self._tokens_list = []
        self._chunk_doc_map = {}
        await self._ensure_built()


class BM25IndexManager:
    """管理所有知识库的 BM25 索引。"""

    def __init__(self):
        self._indexes: dict[str, BM25Index] = {}

    def get(self, kb_id: str) -> BM25Index:
        if kb_id not in self._indexes:
            self._indexes[kb_id] = BM25Index(kb_id)
        return self._indexes[kb_id]

    def remove(self, kb_id: str) -> None:
        self._indexes.pop(kb_id, None)


bm25_manager = BM25IndexManager()
