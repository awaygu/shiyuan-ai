"""SQLite checkpointer for conversation persistence.

提供两个层面的持久化：
1. LangGraph 内置 checkpointer（AsyncSqliteSaver，见 core/agent_graph.py）— 管理 agent 状态
2. 自定义 conversations/messages 表 — 管理对话元数据和消息历史

数据库文件：data/agent_memory.db

连接治理（与主 DB database.py 对齐）：
- 同步 sqlite3，``check_same_thread=False`` 支持跨线程（agent.py 经 ``asyncio.to_thread``
  在工作线程调用，conversations.py 亦经 ``to_thread``）。
- 每次操作新建连接用完即关：写连接每次独立，配合 ``BEGIN IMMEDIATE`` + ``busy_timeout=5000``
  在 DB 层串行化并发写（第二个写事务遇写锁被占由 busy_timeout 重试等待，而非
  ``database is locked`` 报错；每连接独立故无"嵌套事务"问题）。
- 所有写函数用 ``BEGIN IMMEDIATE`` 包裹多语句事务 + ``try/except rollback``，
  全部函数 ``try/finally`` 确保连接 close，异常路径不泄漏连接/不留脏状态。
- ``_cleanup_checkpointer`` 删 LangGraph 的 checkpoints 表，与业务删除用**独立连接**
  （不在同一事务），语义保持不变。
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

DB_PATH: str = ""  # 在 init_db 时设置


def _get_conn() -> sqlite3.Connection:
    """获取 SQLite 连接，设每连接级 PRAGMA。

    - busy_timeout=5000ms：并发写锁竞争时等待重试，避免 ``database is locked``（每连接）。
    - foreign_keys=ON：messages 的外键约束实际生效（每连接）。

    注：WAL 是数据库文件级持久属性（``init_db`` 设置一次后跨连接/进程保留），故
    不在此每连接重设——见 ``init_db``。
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _safe_rollback(conn):
    """回滚事务，吞掉 rollback 自身的异常（连接已坏时 rollback 可能抛 sqlite3.Error）。"""
    try:
        conn.rollback()
    except sqlite3.Error:
        pass


@contextmanager
def _txn():
    """写事务：BEGIN IMMEDIATE + commit/rollback + finally close（每事务独立连接）。"""
    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _conn():
    """读连接：用完即关，无事务（BEGIN 不需要）。"""
    conn = _get_conn()
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str):
    """初始化数据库，创建 conversations 和 messages 表。

    用 ``_conn``（无事务）而非 ``_txn``：``executescript`` 自身会发 COMMIT，
    不能放进 BEGIN IMMEDIATE 事务内；成功即已提交，退出只 close。

    WAL 在此设一次：``journal_mode=WAL`` 是数据库文件级持久属性，设置后跨连接/
    进程保留，故 ``_get_conn`` 不再每连接重设（省一次 PRAGMA 往返）。
    """
    global DB_PATH
    DB_PATH = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    with _conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
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
    logger.info("Memory DB initialized at %s", db_path)


# ── Conversation CRUD ──────────────────────────────────────────


def create_conversation(title: str = "新对话") -> dict:
    """创建新对话，返回 {id, title, created_at, updated_at}。"""
    conv_id = uuid4().hex
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _txn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conv_id, title, now, now),
        )
    return {"id": conv_id, "title": title, "created_at": now, "updated_at": now}


def list_conversations(limit: int = 20, offset: int = 0) -> dict:
    """获取对话列表（排除已删除，按更新时间倒序）。"""
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM conversations WHERE is_deleted = 0").fetchone()[0]
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "WHERE is_deleted = 0 ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    items = [dict(r) for r in rows]
    return {"total": total, "items": items}


def get_conversation(conv_id: str) -> dict | None:
    """获取单个对话信息。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ? AND is_deleted = 0",
            (conv_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_conversation(conv_id: str) -> bool:
    """删除对话及其所有消息，同时清理 LangGraph checkpointer 状态。

    删 messages + conversations 两条 DELETE 在同一 ``BEGIN IMMEDIATE`` 事务内原子完成。
    随后调用 ``_cleanup_checkpointer`` 删 LangGraph checkpoints 表，该操作用**独立连接**
    独立事务（checkpoints 表由 AsyncSqliteSaver 管理，不与业务表同事务）。
    """
    with _txn() as conn:
        # 先检查对话是否存在（BEGIN IMMEDIATE 已拿写锁，读在事务内没问题）。
        row = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND is_deleted = 0",
            (conv_id,),
        ).fetchone()
        if not row:
            # 从 with 块内 return 触发 __exit__ 提交空事务（未写任何行，无害）。
            return False

        # 删除消息 + 对话（原子事务）
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))

    # 清理 LangGraph checkpointer 的 checkpoint 数据（独立连接/独立事务）
    _cleanup_checkpointer(conv_id)

    return True


def _cleanup_checkpointer(conv_id: str):
    """清理 LangGraph checkpointer 中该 thread_id 的所有 checkpoint。

    用独立连接删 checkpoints/checkpoint_writes 表（由 AsyncSqliteSaver 在同库建表），
    与业务删除不在同一事务。表不存在（首次使用 AsyncSqliteSaver 尚未建表）属预期，
    降级为 debug；其余异常记录日志便于排查。
    """
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        # SqliteSaver 的表名为 checkpoints 和 checkpoint_writes
        conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (conv_id,))
        conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = ?", (conv_id,))
        conn.commit()
    except sqlite3.OperationalError as e:
        # checkpoint 表不存在（首次使用时 AsyncSqliteSaver 尚未建表）属预期情况，
        # 精确捕获 OperationalError 并按"no such table"降级为 debug，避免噪音；
        # 其余 OperationalError 仍记录以暴露真实问题。
        if conn is not None:
            _safe_rollback(conn)
        if "no such table" in str(e):
            logger.debug("Checkpoint table not ready yet, skip cleanup: %s", e)
        else:
            logger.warning("Checkpoint cleanup failed: %s", e)
    except Exception as e:
        # 其他未预期异常：回滚后记录日志，不再静默吞。
        if conn is not None:
            _safe_rollback(conn)
        logger.warning("Checkpoint cleanup failed: %s", e)
    finally:
        if conn is not None:
            conn.close()


def update_conversation_title(conv_id: str, title: str) -> bool:
    """更新对话标题。"""
    with _txn() as conn:
        cursor = conn.execute(
            "UPDATE conversations SET title = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
            (title, conv_id),
        )
        updated = cursor.rowcount > 0
    return updated


# ── Message CRUD ───────────────────────────────────────────────


def add_message(
    conv_id: str,
    role: str,
    content: str,
    tool_calls: str | None = None,
    tool_call_id: str | None = None,
    name: str | None = None,
) -> int:
    """添加消息，返回自增 ID。

    INSERT messages + UPDATE conversations.updated_at 两条语句在同一个
    ``BEGIN IMMEDIATE`` 事务内原子完成（任一失败则整体回滚，updated_at 不会单独更新）。
    """
    with _txn() as conn:
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
        msg_id = cursor.lastrowid
    return msg_id


def get_messages(conv_id: str, limit: int = 100) -> list[dict]:
    """获取对话消息（按时间正序）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, role, content, tool_calls, tool_call_id, name, created_at "
            "FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, id ASC LIMIT ?",
            (conv_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def clear_messages(conv_id: str) -> int:
    """清空对话的所有消息。"""
    with _txn() as conn:
        cursor = conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        deleted = cursor.rowcount
    return deleted
