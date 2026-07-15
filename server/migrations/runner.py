"""轻量 async SQL 迁移运行器。

约定：
- 迁移文件为 ``server/migrations/*.sql``，按文件名（字典序）排序依次执行。
- 每个文件名（去 ``.sql`` 后缀）即迁移版本号，例如 ``0001_initial.sql`` -> ``0001_initial``。
- 运行器通过 ``await get_db()`` 拿到实时写连接，因此测试中 ``conftest`` 的
  ``monkeypatch.setattr(db, "DB_PATH", ...)`` + ``setattr(db, "_db", None)``
  仍能让迁移在新库上跑（``_db`` 为写连接变量名，读连接池由 ``close_db()``
  在 ``_db`` 置空前置空，迁移不触及读池）。
- ``schema_version`` 表记录已执行版本；已执行的迁移幂等跳过。
- 每个迁移在单独事务内执行：失败立即 rollback 并抛错，不静默 pass。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# migrations 目录：本文件所在目录。用 Path 解析，避免依赖 cwd。
_MIGRATIONS_DIR = Path(__file__).resolve().parent

# schema_version 表的 DDL。单独建表语句（不放进某个迁移文件），保证运行器
# 在空库上首次运行时即可创建版本表，随后再跑迁移。
_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
)
"""

# 仅允许迁移文件名形如 0001_initial.sql，避免误读 __init__.py 等。
_MIGRATION_RE = re.compile(r"^\d+_.+\.sql$")


async def _ensure_schema_version_table(db: aiosqlite.Connection) -> None:
    await db.execute(_SCHEMA_VERSION_DDL)
    await db.commit()


async def _applied_versions(db: aiosqlite.Connection) -> set[str]:
    cursor = await db.execute("SELECT version FROM schema_version")
    rows = await cursor.fetchall()
    return {row["version"] for row in rows}


def _split_statements(sql: str) -> list[str]:
    """把 SQL 文本按 ';' 切成可执行语句。

    简单实现：按 ';' 分割并去除注释行与空白。迁移文件均为纯 DDL，不包含
    字符串字面量里的分号，因此这种切分方式安全。
    """
    statements: list[str] = []
    for raw in sql.split(";"):
        # 去掉 SQL 行注释（-- ...）与空白
        cleaned_lines = []
        for line in raw.splitlines():
            # 去掉行内注释
            comment_idx = line.find("--")
            if comment_idx != -1:
                line = line[:comment_idx]
            if line.strip():
                cleaned_lines.append(line)
        stmt = "\n".join(cleaned_lines).strip()
        if stmt:
            statements.append(stmt)
    return statements


async def run_migrations(get_db) -> None:
    """执行所有未应用的迁移。

    ``get_db`` 为 ``database.get_db`` 协程工厂（传入而非导入，避免循环依赖，
    也确保拿到 conftest monkeypatch 后的实时连接）。
    """
    db = await get_db()
    await _ensure_schema_version_table(db)
    applied = await _applied_versions(db)

    migration_files = sorted(
        p for p in _MIGRATIONS_DIR.iterdir() if p.is_file() and _MIGRATION_RE.match(p.name)
    )

    pending = [p for p in migration_files if p.stem not in applied]

    for path in pending:
        version = path.stem
        logger.info("Applying migration %s", version)
        sql = path.read_text(encoding="utf-8")
        statements = _split_statements(sql)

        try:
            await db.execute("BEGIN")
            for stmt in statements:
                await db.execute(stmt)
            await db.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (version,),
            )
            await db.commit()
        except Exception:
            # rollback 抛弃本迁移内已执行的语句，并重新抛出让上层感知
            await db.rollback()
            logger.exception("Migration %s failed, rolled back", version)
            raise

    if pending:
        logger.info("Applied %d migration(s): %s", len(pending), ", ".join(p.stem for p in pending))
    else:
        logger.info("Migrations up to date")
