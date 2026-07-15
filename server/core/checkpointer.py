"""SQLite checkpointer for conversation persistence.

提供两个层面的持久化：
1. LangGraph 内置 checkpointer（SqliteSaver）— 管理 agent 状态
2. 自定义 conversations/messages 表 — 管理对话元数据和消息历史

数据库文件：data/agent_memory.db
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

DB_PATH: str = ""  # 在 init_checkpointer 时设置


def _get_conn() -> sqlite3.Connection:
    """获取 SQLite 连接，启用 WAL 模式。"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str):
    """初始化数据库，创建 conversations 和 messages 表。"""
    global DB_PATH
    DB_PATH = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '新对话',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            is_deleted INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL,
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conv
            ON messages(conversation_id, created_at);

        CREATE INDEX IF NOT EXISTS idx_conversations_updated
            ON conversations(updated_at DESC);
    """)
    conn.commit()
    conn.close()
    logger.info("Memory DB initialized at %s", db_path)


def get_sqlite_saver():
    """获取 LangGraph SqliteSaver 实例（用于 checkpointer）。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return SqliteSaver(conn)


# ── Conversation CRUD ──────────────────────────────────────────


def create_conversation(title: str = "新对话") -> dict:
    """创建新对话，返回 {id, title, created_at, updated_at}。"""
    conv_id = uuid4().hex
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (conv_id, title, now, now),
    )
    conn.commit()
    conn.close()
    return {"id": conv_id, "title": title, "created_at": now, "updated_at": now}


def list_conversations(limit: int = 20, offset: int = 0) -> dict:
    """获取对话列表（排除已删除，按更新时间倒序）。"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM conversations WHERE is_deleted = 0").fetchone()[0]
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations "
        "WHERE is_deleted = 0 ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    items = [dict(r) for r in rows]
    return {"total": total, "items": items}


def get_conversation(conv_id: str) -> dict | None:
    """获取单个对话信息。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ? AND is_deleted = 0",
        (conv_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_conversation(conv_id: str) -> bool:
    """删除对话及其所有消息，同时清理 LangGraph checkpointer 状态。"""
    conn = _get_conn()
    # 先检查对话是否存在
    row = conn.execute(
        "SELECT id FROM conversations WHERE id = ? AND is_deleted = 0",
        (conv_id,),
    ).fetchone()
    if not row:
        conn.close()
        return False

    # 删除消息
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    # 删除对话
    conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()

    # 清理 LangGraph checkpointer 的 checkpoint 数据
    _cleanup_checkpointer(conv_id)

    return True


def _cleanup_checkpointer(conv_id: str):
    """清理 LangGraph checkpointer 中该 thread_id 的所有 checkpoint。"""
    try:
        conn = _get_conn()
        # SqliteSaver 的表名为 checkpoints 和 checkpoint_writes
        conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (conv_id,))
        conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = ?", (conv_id,))
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        # checkpoint 表不存在（首次使用时 SqliteSaver 尚未建表）属预期情况，
        # 精确捕获 OperationalError 并按"no such table"降级为 debug，避免噪音；
        # 其余 OperationalError 仍记录以暴露真实问题。
        if "no such table" in str(e):
            logger.debug("Checkpoint table not ready yet, skip cleanup: %s", e)
        else:
            logger.warning("Checkpoint cleanup failed: %s", e)
    except Exception as e:
        # 其他未预期异常不再静默吞，记录日志便于排查。
        logger.warning("Checkpoint cleanup failed: %s", e)


def update_conversation_title(conv_id: str, title: str) -> bool:
    """更新对话标题。"""
    conn = _get_conn()
    cursor = conn.execute(
        "UPDATE conversations SET title = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
        (title, conv_id),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


# ── Message CRUD ───────────────────────────────────────────────


def add_message(
    conv_id: str,
    role: str,
    content: str,
    tool_calls: str | None = None,
    tool_call_id: str | None = None,
    name: str | None = None,
) -> int:
    """添加消息，返回自增 ID。"""
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO messages (conversation_id, role, content, tool_calls, tool_call_id, name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conv_id, role, content, tool_calls, tool_call_id, name),
    )
    # 更新对话的 updated_at
    conn.execute(
        "UPDATE conversations SET updated_at = datetime('now', 'localtime') WHERE id = ?",
        (conv_id,),
    )
    conn.commit()
    msg_id = cursor.lastrowid
    conn.close()
    return msg_id


def get_messages(conv_id: str, limit: int = 100) -> list[dict]:
    """获取对话消息（按时间正序）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, content, tool_calls, tool_call_id, name, created_at "
        "FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, id ASC LIMIT ?",
        (conv_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_messages(conv_id: str) -> int:
    """清空对话的所有消息。"""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount


def get_recent_messages(conv_id: str, n_messages: int = 20) -> list[dict]:
    """获取最近 N 条消息（按时间正序）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, content, tool_calls, tool_call_id, name, created_at "
        "FROM messages WHERE conversation_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (conv_id, n_messages),
    ).fetchall()
    conn.close()
    # 反转为正序
    return list(reversed([dict(r) for r in rows]))
