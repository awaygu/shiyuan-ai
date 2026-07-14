"""轻量 SQL 迁移运行器。

按文件名排序执行 migrations 目录下的 .sql 文件，在 schema_version 表中
记录已执行版本，幂等跳过已执行的迁移。
"""

from __future__ import annotations

from .runner import run_migrations

__all__ = ["run_migrations"]
