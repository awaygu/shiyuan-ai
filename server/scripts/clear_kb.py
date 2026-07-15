#!/usr/bin/env python
"""清空所有知识库数据：文档、向量、存档、数据库记录。"""

import shutil
import sqlite3
import sys
from pathlib import Path

# 从 server/ 根读取 DB_PATH，避免硬编码路径，不依赖 cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from database import DB_PATH  # noqa: E402

base_dir = Path("uploads")

# 1. 删除 uploads/ 下所有知识库目录（12位hex ID）
for d in base_dir.iterdir():
    if d.is_dir() and len(d.name) == 12 and set(d.name) <= set("0123456789abcdef"):
        shutil.rmtree(d, ignore_errors=True)
        print(f"  deleted kb dir: {d}")

# 2. 清空图片存档
archive_dir = base_dir / "archive"
if archive_dir.exists():
    for f in archive_dir.rglob("*"):
        if f.is_file():
            f.unlink()
            print(f"  deleted archive: {f}")

# 3. 清空数据库 KB 相关表
conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()
for table in ["kb_chunks", "kb_documents", "knowledge_bases", "kb_conversations", "kb_messages"]:
    try:
        c.execute(f"DELETE FROM {table}")
        print(f"  cleared table: {table} ({c.rowcount} rows)")
    except Exception as e:
        print(f"  skip table {table}: {e}")
conn.commit()
conn.execute("VACUUM")
conn.close()

print("Done.")
