"""SQLite persistence layer for the news AI system."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "news_ai.db"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS news (
                news_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT,
                content TEXT,
                source TEXT,
                url TEXT,
                published_at TEXT,
                extra TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                article_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                style TEXT,
                news_ids TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS publish_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id TEXT,
                platform TEXT,
                success INTEGER,
                url TEXT,
                timestamp TEXT,
                extra TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS kb_documents (
                doc_id TEXT PRIMARY KEY,
                kb_id TEXT NOT NULL DEFAULT 'default',
                filename TEXT NOT NULL,
                file_type TEXT,
                chunk_count INTEGER DEFAULT 0,
                file_size INTEGER DEFAULT 0,
                upload_time TEXT DEFAULT (datetime('now')),
                status TEXT DEFAULT 'ready'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS kb_chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                chunk_index INTEGER DEFAULT 0,
                page INTEGER DEFAULT 0,
                text TEXT NOT NULL,
                FOREIGN KEY (doc_id) REFERENCES kb_documents(doc_id) ON DELETE CASCADE
            )
        """)
        try:
            await db.execute("ALTER TABLE kb_chunks ADD COLUMN page INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE kb_documents ADD COLUMN kb_id TEXT NOT NULL DEFAULT 'default'")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                kb_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS kb_conversations (
                conv_id TEXT PRIMARY KEY,
                kb_id TEXT NOT NULL,
                title TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (kb_id) REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS kb_messages (
                msg_id TEXT PRIMARY KEY,
                conv_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT DEFAULT '',
                type TEXT DEFAULT 'chat',
                sources TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (conv_id) REFERENCES kb_conversations(conv_id) ON DELETE CASCADE
            )
        """)
        await db.commit()
    logger.info("Database initialized: %s", DB_PATH)


async def save_news(items: list[dict[str, Any]]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM news")
        for item in items:
            extra_json = json.dumps(item.get("extra", {}), ensure_ascii=False)
            await db.execute(
                """
                INSERT OR REPLACE INTO news
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
        await db.commit()


async def append_news(items: list[dict[str, Any]]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        for item in items:
            extra_json = json.dumps(item.get("extra", {}), ensure_ascii=False)
            await db.execute(
                """
                INSERT OR REPLACE INTO news
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
        await db.commit()


async def update_news_content(news_id: str, content: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE news SET content = ? WHERE news_id = ?",
            (content, news_id),
        )
        await db.commit()


async def load_news() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
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


async def save_article(article: dict[str, Any]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM articles ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                "article_id": row["article_id"],
                "title": row["title"],
                "content": row["content"],
                "style": row["style"],
                "news_ids": json.loads(row["news_ids"]) if row["news_ids"] else [],
            })
        return result


async def save_publish_record(record: dict[str, Any]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM publish_log ORDER BY id DESC")
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                "article_id": row["article_id"],
                "platform": row["platform"],
                "success": bool(row["success"]),
                "url": row["url"],
                "timestamp": row["timestamp"],
                "extra": json.loads(row["extra"]) if row["extra"] else {},
            })
        return result


# ── Knowledge Base ─────────────────────────────────────────────

async def save_kb_doc(doc: dict[str, Any]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO kb_documents
                (doc_id, filename, file_type, chunk_count, file_size, upload_time, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc["doc_id"],
                doc["filename"],
                doc.get("file_type", ""),
                doc.get("chunk_count", 0),
                doc.get("file_size", 0),
                doc.get("upload_time", ""),
                doc.get("status", "ready"),
            ),
        )
        await db.commit()


async def load_kb_docs() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM kb_documents ORDER BY upload_time DESC")
        rows = await cursor.fetchall()
        return [
            {
                "doc_id": row["doc_id"],
                "filename": row["filename"],
                "file_type": row["file_type"],
                "chunk_count": row["chunk_count"],
                "file_size": row["file_size"],
                "upload_time": row["upload_time"],
                "status": row["status"],
            }
            for row in rows
        ]


async def delete_kb_doc(doc_id: str) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT chunk_id FROM kb_chunks WHERE doc_id = ?", (doc_id,)
        )
        rows = await cursor.fetchall()
        chunk_ids = [row["chunk_id"] for row in rows]
        await db.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (doc_id,))
        await db.execute("DELETE FROM kb_documents WHERE doc_id = ?", (doc_id,))
        await db.commit()
    return chunk_ids


async def save_kb_chunks(chunks: list[dict[str, Any]]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        result = {}
        for cid in chunk_ids:
            cursor = await db.execute(
                "SELECT c.chunk_id, c.text, c.page, c.doc_id, d.filename "
                "FROM kb_chunks c LEFT JOIN kb_documents d ON c.doc_id = d.doc_id "
                "WHERE c.chunk_id = ?",
                (cid,),
            )
            row = await cursor.fetchone()
            if row:
                result[cid] = {
                    "chunk_id": row["chunk_id"],
                    "text": row["text"],
                    "page": row["page"],
                    "doc_id": row["doc_id"],
                    "filename": row["filename"],
                }
        return result


# ── Knowledge Bases ────────────────────────────────────────────

async def create_kb(kb: dict[str, Any]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO knowledge_bases (kb_id, name, description) VALUES (?, ?, ?)",
            (kb["kb_id"], kb["name"], kb.get("description", "")),
        )
        await db.commit()


async def load_kbs() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
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


async def delete_kb(kb_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM kb_messages WHERE conv_id IN (SELECT conv_id FROM kb_conversations WHERE kb_id = ?)", (kb_id,))
        await db.execute("DELETE FROM kb_conversations WHERE kb_id = ?", (kb_id,))
        chunk_ids = []
        cursor = await db.execute("SELECT chunk_id FROM kb_chunks WHERE doc_id IN (SELECT doc_id FROM kb_documents WHERE kb_id = ?)", (kb_id,))
        rows = await cursor.fetchall()
        chunk_ids = [row["chunk_id"] for row in rows]
        await db.execute("DELETE FROM kb_chunks WHERE doc_id IN (SELECT doc_id FROM kb_documents WHERE kb_id = ?)", (kb_id,))
        await db.execute("DELETE FROM kb_documents WHERE kb_id = ?", (kb_id,))
        await db.execute("DELETE FROM knowledge_bases WHERE kb_id = ?", (kb_id,))
        await db.commit()
    return chunk_ids


async def save_kb_doc(doc: dict[str, Any]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO kb_documents
                (doc_id, kb_id, filename, file_type, chunk_count, file_size, upload_time, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        await db.commit()


async def load_kb_docs(kb_id: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM kb_documents WHERE kb_id = ? ORDER BY upload_time DESC", (kb_id,))
        rows = await cursor.fetchall()
        return [
            {
                "doc_id": row["doc_id"],
                "kb_id": row["kb_id"],
                "filename": row["filename"],
                "file_type": row["file_type"],
                "chunk_count": row["chunk_count"],
                "file_size": row["file_size"],
                "upload_time": row["upload_time"],
                "status": row["status"],
            }
            for row in rows
        ]


async def delete_kb_doc(doc_id: str) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT chunk_id FROM kb_chunks WHERE doc_id = ?", (doc_id,)
        )
        rows = await cursor.fetchall()
        chunk_ids = [row["chunk_id"] for row in rows]
        await db.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (doc_id,))
        await db.execute("DELETE FROM kb_documents WHERE doc_id = ?", (doc_id,))
        await db.commit()
    return chunk_ids


# ── KB Conversations ──────────────────────────────────────────

async def create_conversation(conv: dict[str, Any]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM kb_messages WHERE conv_id = ?", (conv_id,))
        await db.execute("DELETE FROM kb_conversations WHERE conv_id = ?", (conv_id,))
        await db.commit()


async def save_message(msg: dict[str, Any]) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
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


async def load_messages(conv_id: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
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
