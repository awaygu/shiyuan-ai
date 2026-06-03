"""DashScope text-embedding-v4 client."""

from __future__ import annotations

import logging
from typing import Sequence

import dashscope
from dashscope import TextEmbedding

from config import DASHSCOPE_API_KEY, KB_EMBEDDING_DIM, KB_EMBEDDING_MODEL

logger = logging.getLogger(__name__)

EMBEDDING_DIM = KB_EMBEDDING_DIM
EMBEDDING_MODEL = KB_EMBEDDING_MODEL
BATCH_SIZE = 10


class DashScopeEmbedding:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or DASHSCOPE_API_KEY
        dashscope.api_key = self.api_key

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            resp = TextEmbedding.call(model=EMBEDDING_MODEL, input=batch)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"DashScope embedding failed: {resp.status_code} - {resp.message}"
                )
            batch_embs = [item["embedding"] for item in resp.output["embeddings"]]
            all_embeddings.extend(batch_embs)
        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        result = self.embed([text])
        if not result:
            raise RuntimeError("Empty embedding result for query")
        return result[0]
