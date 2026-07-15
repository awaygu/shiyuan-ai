"""SQLite persistence layer for the news AI system.

读写分离：写连接（``_db``，单连接）走 ``get_db()``，读连接走 ``get_read_db()``
（独立读连接池，WAL 下读不阻塞写）。

- ``get_db()``：写连接，惰性建立，设 row_factory + WAL/busy_timeout/foreign_keys
  三条 PRAGMA。迁移与所有写/复合写函数共用此连接。
- ``get_read_db()``：异步上下文管理器，从读连接池借一个连接（池空且未达上限
  时新建，设 row_factory + WAL），用完归还池。池大小由 ``config.KB_DB_POOL_SIZE``
  控制。读连接复用而非每次新建，但分页等需同一快照的多次 SELECT 在一次借用内
  复用同一连接。

测试隔离：``close_db()`` 同时关闭写连接 + 清空读连接池（关闭所有读连接并置空
池与信号量），保证 ``monkeypatch db.DB_PATH`` 后下一次 ``get_read_db()`` 按新路径
重建。``_db`` 变量名保持不变以兼容 conftest 的 ``monkeypatch.setattr(db, "_db", None)``。
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("NEWS_AI_DB_PATH", str(Path(__file__).parent / "news_ai.db")))

# 写连接（单连接，迁移与所有写函数共用）
_db: aiosqlite.Connection | None = None

# 读连接池：_read_pool 缓存空闲读连接；_read_semaphore 限制并发借出数（即池大小）。
# 池大小在首次建池时按 config.KB_DB_POOL_SIZE 固定，close_db() 清空后下次重建。
_read_pool: list[aiosqlite.Connection] | None = None
_read_semaphore: Any = None  # asyncio.Semaphore | None


def _pool_size() -> int:
    """读连接池大小，运行时从 config 读取（便于测试 monkeypatch）。"""
    try:
        from config import KB_DB_POOL_SIZE

        return max(1, int(KB_DB_POOL_SIZE))
    except Exception:
        # config 不可用时回退默认值，避免导入期循环依赖导致建池失败
        return 8


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA busy_timeout=5000")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def _new_read_connection() -> aiosqlite.Connection:
    """新建一条读连接：设 row_factory + WAL（只读无需 busy_timeout/foreign_keys，但设上无害）。"""
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


@asynccontextmanager
async def get_read_db() -> Any:
    """借一个读连接（异步上下文管理器）。

    从读连接池取空闲连接；池空且未达上限时新建。用完归还池（不关闭），
    供后续读复用。WAL 下读不阻塞写，多个并发读各取独立连接。
    需同一快照的多次 SELECT（如分页 COUNT + 页查询）在一次借用内复用同一连接。
    """
    global _read_pool, _read_semaphore
    import asyncio

    if _read_pool is None or _read_semaphore is None:
        _read_pool = []
        _read_semaphore = asyncio.Semaphore(_pool_size())

    # 限流：最多 pool_size 个读连接同时借出
    await _read_semaphore.acquire()
    conn: aiosqlite.Connection | None = None
    try:
        if _read_pool:
            conn = _read_pool.pop()
        else:
            conn = await _new_read_connection()
        yield conn
    finally:
        # 归还到池（而非关闭），供后续读复用；归还前重置连接无状态可清，直接放回
        if _read_pool is not None and conn is not None:
            _read_pool.append(conn)
        _read_semaphore.release()


async def close_db() -> None:
    """关闭写连接 + 清空读连接池（关闭所有读连接并置空池与信号量）。

    测试中 monkeypatch db.DB_PATH 后调用本函数，确保下一次 get_read_db()
    按新路径重建池；_db 置 None 让 get_db() 重建写连接。
    """
    global _db, _read_pool, _read_semaphore
    if _db is not None:
        await _db.close()
        _db = None
    if _read_pool is not None:
        for conn in _read_pool:
            try:
                await conn.close()
            except Exception:
                logger.warning("Failed to close a read connection", exc_info=True)
        _read_pool = None
    _read_semaphore = None


async def init_db() -> None:
    """初始化数据库 schema。

    委托给 migrations 运行器：创建 schema_version 表后，按版本顺序执行
    migrations/*.sql 中未应用的迁移。原 init_db 里的 8 个 CREATE TABLE
    及 4 个 try/except ALTER TABLE 已迁入 migrations/0001_initial.sql，
    其中 source_url 提升进 kb_documents 的 CREATE TABLE（消除原本仅靠
    ALTER 存在的隐患）。

    运行器通过 get_db() 拿实时连接，测试中 conftest 对 DB_PATH/_db 的
    monkeypatch 在此处生效，每个测试的空库都会正确跑 0001_initial。

    读连接池惰性建立（首次 get_read_db() 时按 config.KB_DB_POOL_SIZE 建池），
    此处不预建；close_db() 会清空池。
    """
    from migrations.runner import run_migrations

    await run_migrations(get_db)
    logger.info("Database initialized: %s", DB_PATH)


@asynccontextmanager
async def transaction() -> Any:
    """写事务上下文管理器：拿写连接并 BEGIN IMMEDIATE（拿写锁串行化写事务）。

    供调用方把"多步写 + 其间的读"包进同一事务，退出时自动 commit/rollback：
    正常退出 commit，抛异常 rollback 并重新抛出。本任务只提供能力，不自行调用。

    用法::

        async with transaction() as db:
            await db.execute("UPDATE ...")
            await db.execute("DELETE ...")
    """
    db = await get_db()
    await db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def upsert_news(items: list[dict[str, Any]]) -> int:
    """增量入库：已存在的 news_id 跳过（INSERT OR IGNORE），返回实际新增条数。

    替代 save_news 的"DELETE 全量 + INSERT"写法，避免长跑后写入开销线性增长、
    以及重复 refresh 导致历史数据被全量重写。调用方负责去重后传入新增条目。
    """
    if not items:
        return 0
    db = await get_db()
    inserted = 0
    for item in items:
        extra_json = json.dumps(item.get("extra", {}), ensure_ascii=False)
        cur = await db.execute(
            """
            INSERT OR IGNORE INTO news
                (news_id, title, summary, content, source, url, published_at, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["news_id"],
                item["title"],
                item.get("summary", ""),
                item.get("content", ""),
                item.get("source", ""),
                item.get("url", ""),
                item.get("published_at", ""),
                extra_json,
            ),
        )
        inserted += cur.rowcount
    await db.commit()
    return inserted


async def upsert_news_returning(items: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """增量入库并返回新增 news_id 列表（供任务 7 锁收窄使用）。

    与 upsert_news 同语义（INSERT OR IGNORE 跳过已存在 id），但用
    ``INSERT ... RETURNING news_id`` 拿回真正新增的 news_id 列表——
    INSERT OR IGNORE 被忽略的行不 RETURNING，故只含实际插入的 id。

    返回 ``(inserted_count, inserted_news_ids)``。空入参返回 ``(0, [])``。
    保持 upsert_news 返回 int 不变，向后兼容现有调用方。
    """
    if not items:
        return 0, []
    db = await get_db()
    inserted_ids: list[str] = []
    for item in items:
        extra_json = json.dumps(item.get("extra", {}), ensure_ascii=False)
        cur = await db.execute(
            """
            INSERT OR IGNORE INTO news
                (news_id, title, summary, content, source, url, published_at, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING news_id
            """,
            (
                item["news_id"],
                item["title"],
                item.get("summary", ""),
                item.get("content", ""),
                item.get("source", ""),
                item.get("url", ""),
                item.get("published_at", ""),
                extra_json,
            ),
        )
        rows = await cur.fetchall()
        for row in rows:
            inserted_ids.append(row["news_id"])
    await db.commit()
    return len(inserted_ids), inserted_ids


async def update_news_content(news_id: str, content: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE news SET content = ? WHERE news_id = ?",
        (content, news_id),
    )
    await db.commit()


async def clear_news_content_by_source(source: str) -> int:
    db = await get_db()
    cursor = await db.execute(
        "UPDATE news SET content = '' WHERE source = ?",
        (source,),
    )
    await db.commit()
    return cursor.rowcount


async def load_news() -> list[dict[str, Any]]:
    async with get_read_db() as db:
        cursor = await db.execute("SELECT * FROM news ORDER BY published_at DESC")
        rows = await cursor.fetchall()
    result = []
    for row in rows:
        item = {
            "news_id": row["news_id"],
            "title": row["title"],
            "summary": row["summary"],
            "content": row["content"],
            "source": row["source"],
            "url": row["url"],
            "published_at": row["published_at"],
            "extra": json.loads(row["extra"]) if row["extra"] else {},
        }
        result.append(item)
    return result


def _row_to_news(row: aiosqlite.Row) -> dict[str, Any]:
    """将 news 表的行反序列化为 dict（extra JSON 解码）。"""
    return {
        "news_id": row["news_id"],
        "title": row["title"],
        "summary": row["summary"],
        "content": row["content"],
        "source": row["source"],
        "url": row["url"],
        "published_at": row["published_at"],
        "extra": json.loads(row["extra"]) if row["extra"] else {},
    }


async def get_news(news_id: str) -> dict[str, Any] | None:
    """按 news_id 单条查询，未找到返回 None。extra 自动反序列化。"""
    async with get_read_db() as db:
        cursor = await db.execute("SELECT * FROM news WHERE news_id = ?", (news_id,))
        row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_news(row)


async def get_news_batch(news_ids: list[str]) -> list[dict[str, Any]]:
    """批量按 news_id 查询，返回 DB 中存在的全部条目（顺序按 published_at DESC）。"""
    if not news_ids:
        return []
    async with get_read_db() as db:
        placeholders = ",".join("?" for _ in news_ids)
        cursor = await db.execute(
            f"SELECT * FROM news WHERE news_id IN ({placeholders}) ORDER BY published_at DESC",
            news_ids,
        )
        rows = await cursor.fetchall()
    return [_row_to_news(row) for row in rows]


async def list_news(
    source: str | None = None, offset: int = 0, limit: int = 20
) -> tuple[list[dict[str, Any]], int]:
    """分页列表 + total。source 为 None 查全部；ORDER BY published_at DESC。

    COUNT + 分页两次 SELECT 在一次读连接借用内复用同一连接（同一快照）。
    """
    async with get_read_db() as db:
        if source is not None:
            cursor = await db.execute("SELECT COUNT(*) AS c FROM news WHERE source = ?", (source,))
            total = (await cursor.fetchone())["c"]
            cursor = await db.execute(
                "SELECT * FROM news WHERE source = ? ORDER BY published_at DESC LIMIT ? OFFSET ?",
                (source, limit, offset),
            )
        else:
            cursor = await db.execute("SELECT COUNT(*) AS c FROM news")
            total = (await cursor.fetchone())["c"]
            cursor = await db.execute(
                "SELECT * FROM news ORDER BY published_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cursor.fetchall()
    return [_row_to_news(row) for row in rows], total


async def news_id_exists_batch(news_ids: list[str]) -> set[str]:
    """返回 news_ids 中已存在于 DB 的子集（去重判断用，比逐条 any() 快）。"""
    if not news_ids:
        return set()
    async with get_read_db() as db:
        placeholders = ",".join("?" for _ in news_ids)
        cursor = await db.execute(
            f"SELECT news_id FROM news WHERE news_id IN ({placeholders})",
            news_ids,
        )
        rows = await cursor.fetchall()
    return {row["news_id"] for row in rows}


async def delete_all_news() -> None:
    """清空 news 表。用于 refresh_news 的"重新刷新全部"语义。"""
    db = await get_db()
    await db.execute("DELETE FROM news")
    await db.commit()


async def get_news_sources() -> list[str]:
    """返回 news 表中出现过的不重复 source 列表（用于启动时检测过期 source 格式）。"""
    async with get_read_db() as db:
        cursor = await db.execute("SELECT DISTINCT source FROM news")
        rows = await cursor.fetchall()
    return [row["source"] for row in rows if row["source"] is not None]


async def save_article(article: dict[str, Any]) -> None:
    db = await get_db()
    news_ids_json = json.dumps(article.get("news_ids", []), ensure_ascii=False)
    await db.execute(
        """
        INSERT OR REPLACE INTO articles (article_id, title, content, style, news_ids)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            article["article_id"],
            article["title"],
            article.get("content", ""),
            article.get("style", ""),
            news_ids_json,
        ),
    )
    await db.commit()


async def load_articles() -> list[dict[str, Any]]:
    async with get_read_db() as db:
        cursor = await db.execute("SELECT * FROM articles ORDER BY created_at DESC")
        rows = await cursor.fetchall()
    return [_row_to_article(row) for row in rows]


def _row_to_article(row: aiosqlite.Row) -> dict[str, Any]:
    """将 articles 表的行反序列化为 dict（news_ids JSON 解码）。"""
    return {
        "article_id": row["article_id"],
        "title": row["title"],
        "content": row["content"],
        "style": row["style"],
        "news_ids": json.loads(row["news_ids"]) if row["news_ids"] else [],
    }


async def get_article(article_id: str) -> dict[str, Any] | None:
    """按 article_id 单条查询，未找到返回 None。"""
    async with get_read_db() as db:
        cursor = await db.execute("SELECT * FROM articles WHERE article_id = ?", (article_id,))
        row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_article(row)


async def list_articles(offset: int = 0, limit: int = 20) -> tuple[list[dict[str, Any]], int]:
    """分页列表 + total，ORDER BY created_at DESC。

    COUNT + 分页两次 SELECT 在一次读连接借用内复用同一连接（同一快照）。
    """
    async with get_read_db() as db:
        cursor = await db.execute("SELECT COUNT(*) AS c FROM articles")
        total = (await cursor.fetchone())["c"]
        cursor = await db.execute(
            "SELECT * FROM articles ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
    return [_row_to_article(row) for row in rows], total


async def save_publish_record(record: dict[str, Any]) -> None:
    db = await get_db()
    extra_json = json.dumps(record.get("extra", {}), ensure_ascii=False)
    await db.execute(
        """
        INSERT INTO publish_log (article_id, platform, success, url, timestamp, extra)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            record["article_id"],
            record["platform"],
            int(record.get("success", False)),
            record.get("url", ""),
            record.get("timestamp", ""),
            extra_json,
        ),
    )
    await db.commit()


async def load_publish_log() -> list[dict[str, Any]]:
    async with get_read_db() as db:
        cursor = await db.execute("SELECT * FROM publish_log ORDER BY id DESC")
        rows = await cursor.fetchall()
    return [_row_to_publish_log(row) for row in rows]


def _row_to_publish_log(row: aiosqlite.Row) -> dict[str, Any]:
    """将 publish_log 表的行反序列化为 dict（success 转 bool，extra JSON 解码）。"""
    return {
        "article_id": row["article_id"],
        "platform": row["platform"],
        "success": bool(row["success"]),
        "url": row["url"],
        "timestamp": row["timestamp"],
        "extra": json.loads(row["extra"]) if row["extra"] else {},
    }


async def list_publish_log(offset: int = 0, limit: int = 20) -> tuple[list[dict[str, Any]], int]:
    """分页列表 + total，ORDER BY id DESC（最新优先）。

    COUNT + 分页两次 SELECT 在一次读连接借用内复用同一连接（同一快照）。
    """
    async with get_read_db() as db:
        cursor = await db.execute("SELECT COUNT(*) AS c FROM publish_log")
        total = (await cursor.fetchone())["c"]
        cursor = await db.execute(
            "SELECT * FROM publish_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
    return [_row_to_publish_log(row) for row in rows], total


# ── Knowledge Base ─────────────────────────────────────────────


async def save_kb_doc(doc: dict[str, Any]) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT OR REPLACE INTO kb_documents
            (doc_id, kb_id, filename, file_type, chunk_count, file_size, upload_time, status, summary, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc["doc_id"],
            doc.get("kb_id", "default"),
            doc["filename"],
            doc.get("file_type", ""),
            doc.get("chunk_count", 0),
            doc.get("file_size", 0),
            doc.get("upload_time", ""),
            doc.get("status", "ready"),
            doc.get("summary", ""),
            doc.get("source_url", ""),
        ),
    )
    await db.commit()


async def rename_kb_doc(doc_id: str, filename: str) -> bool:
    db = await get_db()
    cursor = await db.execute("SELECT doc_id FROM kb_documents WHERE doc_id = ?", (doc_id,))
    if not await cursor.fetchone():
        return False
    await db.execute("UPDATE kb_documents SET filename = ? WHERE doc_id = ?", (filename, doc_id))
    await db.commit()
    return True


async def load_kb_docs(kb_id: str = "") -> list[dict[str, Any]]:
    async with get_read_db() as db:
        if kb_id:
            cursor = await db.execute("SELECT * FROM kb_documents WHERE kb_id = ? ORDER BY upload_time DESC", (kb_id,))
        else:
            cursor = await db.execute("SELECT * FROM kb_documents ORDER BY upload_time DESC")
        rows = await cursor.fetchall()
    return [
        {
            "doc_id": row["doc_id"],
            "kb_id": row["kb_id"] if "kb_id" in row else "",
            "filename": row["filename"],
            "file_type": row["file_type"],
            "chunk_count": row["chunk_count"],
            "file_size": row["file_size"],
            "upload_time": row["upload_time"],
            "status": row["status"],
            "summary": row["summary"] if "summary" in row else "",
            "source_url": row["source_url"] if "source_url" in row else "",
        }
        for row in rows
    ]


async def delete_kb_doc(doc_id: str) -> list[str]:
    db = await get_db()
    cursor = await db.execute("SELECT chunk_id FROM kb_chunks WHERE doc_id = ?", (doc_id,))
    rows = await cursor.fetchall()
    chunk_ids = [row["chunk_id"] for row in rows]
    await db.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (doc_id,))
    await db.execute("DELETE FROM kb_documents WHERE doc_id = ?", (doc_id,))
    await db.commit()
    return chunk_ids


async def save_kb_chunks(chunks: list[dict[str, Any]]) -> None:
    db = await get_db()
    for chunk in chunks:
        await db.execute(
            """
            INSERT OR REPLACE INTO kb_chunks (chunk_id, doc_id, chunk_index, page, text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                chunk["chunk_id"],
                chunk["doc_id"],
                chunk.get("chunk_index", 0),
                chunk.get("page", 0),
                chunk["text"],
            ),
        )
    await db.commit()


async def load_kb_chunk_texts(chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not chunk_ids:
        return {}
    async with get_read_db() as db:
        placeholders = ",".join("?" for _ in chunk_ids)
        cursor = await db.execute(
            f"SELECT c.chunk_id, c.text, c.page, c.doc_id, d.filename "
            f"FROM kb_chunks c LEFT JOIN kb_documents d ON c.doc_id = d.doc_id "
            f"WHERE c.chunk_id IN ({placeholders})",
            chunk_ids,
        )
        rows = await cursor.fetchall()
    result = {}
    for row in rows:
        result[row["chunk_id"]] = {
            "chunk_id": row["chunk_id"],
            "text": row["text"],
            "page": row["page"],
            "doc_id": row["doc_id"],
            "filename": row["filename"],
        }
    return result


async def load_kb_all_chunks(kb_id: str) -> list[dict[str, Any]]:
    """加载某个知识库下的所有 chunk（用于 BM25 索引构建）。"""
    if not kb_id:
        return []
    async with get_read_db() as db:
        cursor = await db.execute(
            """
            SELECT c.chunk_id, c.text, c.page, c.doc_id, d.filename
            FROM kb_chunks c
            LEFT JOIN kb_documents d ON c.doc_id = d.doc_id
            WHERE d.kb_id = ?
            ORDER BY c.doc_id, c.chunk_index
            """,
            (kb_id,),
        )
        rows = await cursor.fetchall()
    return [
        {
            "chunk_id": row["chunk_id"],
            "text": row["text"],
            "page": row["page"],
            "doc_id": row["doc_id"],
            "filename": row["filename"],
        }
        for row in rows
    ]


# ── Knowledge Bases ────────────────────────────────────────────


async def create_kb(kb: dict[str, Any]) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO knowledge_bases (kb_id, name, description) VALUES (?, ?, ?)",
        (kb["kb_id"], kb["name"], kb.get("description", "")),
    )
    await db.commit()


async def load_kbs() -> list[dict[str, Any]]:
    async with get_read_db() as db:
        cursor = await db.execute("SELECT * FROM knowledge_bases ORDER BY created_at DESC")
        rows = await cursor.fetchall()
    return [
        {
            "kb_id": row["kb_id"],
            "name": row["name"],
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


async def load_kb(kb_id: str) -> dict[str, Any] | None:
    async with get_read_db() as db:
        cursor = await db.execute("SELECT * FROM knowledge_bases WHERE kb_id = ?", (kb_id,))
        row = await cursor.fetchone()
    if not row:
        return None
    return {
        "kb_id": row["kb_id"],
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def update_kb(kb_id: str, name: str | None = None, description: str | None = None) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute("SELECT name, description FROM knowledge_bases WHERE kb_id = ?", (kb_id,))
    existing = await cursor.fetchone()
    if not existing:
        return None
    new_name = name if name is not None else existing["name"]
    new_desc = description if description is not None else existing["description"]
    await db.execute(
        "UPDATE knowledge_bases SET name = ?, description = ?, updated_at = datetime('now') WHERE kb_id = ?",
        (new_name, new_desc, kb_id),
    )
    await db.commit()
    return {"kb_id": kb_id, "name": new_name, "description": new_desc}


async def delete_kb(kb_id: str) -> list[str]:
    db = await get_db()
    await db.execute(
        "DELETE FROM kb_messages WHERE conv_id IN (SELECT conv_id FROM kb_conversations WHERE kb_id = ?)", (kb_id,)
    )
    await db.execute("DELETE FROM kb_conversations WHERE kb_id = ?", (kb_id,))
    cursor = await db.execute(
        "SELECT chunk_id FROM kb_chunks WHERE doc_id IN (SELECT doc_id FROM kb_documents WHERE kb_id = ?)", (kb_id,)
    )
    rows = await cursor.fetchall()
    chunk_ids = [row["chunk_id"] for row in rows]
    await db.execute(
        "DELETE FROM kb_chunks WHERE doc_id IN (SELECT doc_id FROM kb_documents WHERE kb_id = ?)", (kb_id,)
    )
    await db.execute("DELETE FROM kb_documents WHERE kb_id = ?", (kb_id,))
    await db.execute("DELETE FROM knowledge_bases WHERE kb_id = ?", (kb_id,))
    await db.commit()
    return chunk_ids


# ── KB Conversations ──────────────────────────────────────────


async def create_conversation(conv: dict[str, Any]) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO kb_conversations (conv_id, kb_id, title) VALUES (?, ?, ?)",
        (conv["conv_id"], conv["kb_id"], conv.get("title", "")),
    )
    await db.execute(
        "UPDATE knowledge_bases SET updated_at = datetime('now') WHERE kb_id = ?",
        (conv["kb_id"],),
    )
    await db.commit()


async def load_conversations(kb_id: str) -> list[dict[str, Any]]:
    async with get_read_db() as db:
        cursor = await db.execute("SELECT * FROM kb_conversations WHERE kb_id = ? ORDER BY created_at DESC", (kb_id,))
        rows = await cursor.fetchall()
    return [
        {
            "conv_id": row["conv_id"],
            "kb_id": row["kb_id"],
            "title": row["title"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


async def delete_conversation(conv_id: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM kb_messages WHERE conv_id = ?", (conv_id,))
    await db.execute("DELETE FROM kb_conversations WHERE conv_id = ?", (conv_id,))
    await db.commit()


async def save_message(msg: dict[str, Any]) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO kb_messages (msg_id, conv_id, role, content, type, sources) VALUES (?, ?, ?, ?, ?, ?)",
        (
            msg["msg_id"],
            msg["conv_id"],
            msg["role"],
            msg.get("content", ""),
            msg.get("type", "chat"),
            msg.get("sources", ""),
        ),
    )
    await db.commit()


async def clear_kb_messages(conv_id: str) -> int:
    db = await get_db()
    cursor = await db.execute("DELETE FROM kb_messages WHERE conv_id = ?", (conv_id,))
    await db.commit()
    return cursor.rowcount


async def load_messages(conv_id: str, limit: int = 0) -> list[dict[str, Any]]:
    async with get_read_db() as db:
        if limit > 0:
            # 取最近 limit 条，再按时间正序返回，保证流式上下文只看近期历史
            cursor = await db.execute(
                "SELECT * FROM (SELECT * FROM kb_messages WHERE conv_id = ? ORDER BY created_at DESC LIMIT ?) ORDER BY created_at ASC",
                (conv_id, limit),
            )
        else:
            cursor = await db.execute("SELECT * FROM kb_messages WHERE conv_id = ? ORDER BY created_at ASC", (conv_id,))
        rows = await cursor.fetchall()
    return [
        {
            "msg_id": row["msg_id"],
            "conv_id": row["conv_id"],
            "role": row["role"],
            "content": row["content"],
            "type": row["type"],
            "sources": row["sources"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
