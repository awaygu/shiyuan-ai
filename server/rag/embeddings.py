"""DashScope text-embedding-v4 client."""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import dashscope
from dashscope import TextEmbedding

from config import DASHSCOPE_API_KEY, KB_EMBEDDING_DIM, KB_EMBEDDING_MODEL

logger = logging.getLogger(__name__)

EMBEDDING_DIM = KB_EMBEDDING_DIM
EMBEDDING_MODEL = KB_EMBEDDING_MODEL
BATCH_SIZE = 10
RATE_LIMIT_CALLS = 5
RATE_LIMIT_WINDOW = 1.0

# 用于嵌入的线程池；Python 3.10 的 asyncio.to_thread 不拷贝 contextvars，
# 这里通过 submit + copy_context().run 保证 LangSmith trace 上下文能传递到子线程。
_embed_executor = ThreadPoolExecutor(thread_name_prefix="dashscope_embed_")


class DashScopeEmbedding:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or DASHSCOPE_API_KEY
        dashscope.api_key = self.api_key
        self._call_timestamps: list[float] = []

    def _rate_limit_wait(self) -> None:
        now = time.monotonic()
        self._call_timestamps = [t for t in self._call_timestamps if now - t < RATE_LIMIT_WINDOW]
        if len(self._call_timestamps) >= RATE_LIMIT_CALLS:
            sleep_time = RATE_LIMIT_WINDOW - (now - self._call_timestamps[0])
            if sleep_time > 0:
                logger.debug("Rate limit: sleeping %.2fs", sleep_time)
                time.sleep(sleep_time)
        self._call_timestamps.append(time.monotonic())

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            self._rate_limit_wait()
            resp = TextEmbedding.call(model=EMBEDDING_MODEL, input=batch)
            if resp.status_code != 200:
                raise RuntimeError(f"DashScope embedding failed: {resp.status_code} - {resp.message}")
            batch_embs = [item["embedding"] for item in resp.output["embeddings"]]
            all_embeddings.extend(batch_embs)
        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        result = self.embed([text])
        if not result:
            raise RuntimeError("Empty embedding result for query")
        return result[0]

    async def embed_async(self, texts: Sequence[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()
        return await loop.run_in_executor(_embed_executor, ctx.run, self.embed, texts)

    async def embed_query_async(self, text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()
        return await loop.run_in_executor(_embed_executor, ctx.run, self.embed_query, text)
