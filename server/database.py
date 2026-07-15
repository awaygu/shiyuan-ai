"""SQLite persistence layer for the news AI system."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("NEWS_AI_DB_PATH", str(Path(__file__).parent / "news_ai.db")))

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA busy_timeout=5000")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def init_db() -> None:
    """初始化数据库 schema。

    委托给 migrations 运行器：创建 schema_version 表后，按版本顺序执行
    migrations/*.sql 中未应用的迁移。原 init_db 里的 8 个 CREATE TABLE
    及 4 个 try/except ALTER TABLE 已迁入 migrations/0001_initial.sql，
    其中 source_url 提升进 kb_documents 的 CREATE TABLE（消除原本仅靠
    ALTER 存在的隐患）。

    运行器通过 get_db() 拿实时连接，测试中 conftest 对 DB_PATH/_db 的
    monkeypatch 在此处生效，每个测试的空库都会正确跑 0001_initial。
    """
    from migrations.runner import run_migrations

    await run_migrations(get_db)
    logger.info("Database initialized: %s", DB_PATH)


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
    db = await get_db()
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
    db = await get_db()
    cursor = await db.execute("SELECT * FROM news WHERE news_id = ?", (news_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_news(row)


async def get_news_batch(news_ids: list[str]) -> list[dict[str, Any]]:
    """批量按 news_id 查询，返回 DB 中存在的全部条目（顺序按 published_at DESC）。"""
    if not news_ids:
        return []
    db = await get_db()
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
    """分页列表 + total。source 为 None 查全部；ORDER BY published_at DESC。"""
    db = await get_db()
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
    db = await get_db()
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
    db = await get_db()
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
    db = await get_db()
    cursor = await db.execute("SELECT * FROM articles ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    result = []
    for row in rows:
        result.append(_row_to_article(row))
    return result


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
    db = await get_db()
    cursor = await db.execute("SELECT * FROM articles WHERE article_id = ?", (article_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_article(row)


async def list_articles(offset: int = 0, limit: int = 20) -> tuple[list[dict[str, Any]], int]:
    """分页列表 + total，ORDER BY created_at DESC。"""
    db = await get_db()
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
    db = await get_db()
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
    """分页列表 + total，ORDER BY id DESC（最新优先）。"""
    db = await get_db()
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
    db = await get_db()
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
    db = await get_db()
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
    db = await get_db()
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
    db = await get_db()
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
    db = await get_db()
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
    db = await get_db()
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
    db = await get_db()
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
