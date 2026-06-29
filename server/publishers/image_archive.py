"""通用图片存档模块 — 供各平台发布器复用文生图结果。

每张生成的图片按「kind + 内容哈希」落盘，所有平台共享同一存档池。
同一篇文章发到不同平台时，封面/正文图会直接复用，省去重复调用 DashScope。
存档目录：{UPLOAD_DIR}/archive/。
可通过环境变量 IMAGE_ARCHIVE=0 全局关闭存档。
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path

from config import UPLOAD_DIR

logger = logging.getLogger(__name__)

_ARCHIVE_DIR = Path(UPLOAD_DIR) / "archive"
_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def archive_enabled() -> bool:
    """检查是否开启图片存档。"""
    return os.getenv("IMAGE_ARCHIVE", "1") == "1"


def archive_key(kind: str, *parts: str) -> Path | None:
    """按内容生成存档文件路径。存档关闭时返回 None。

    kind='cover' 用 (title) 做 key；kind='inline' 用 (section_title, text) 做 key。
    所有 parts 会被 join 后 sha1 哈希，保证同内容同路径。
    """
    if not archive_enabled():
        return None
    raw = "\x00".join(p.strip() for p in parts if p)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return _ARCHIVE_DIR / f"{kind}_{digest}.jpg"


def try_read_archive(archive_path: Path | None, output_path: Path) -> bool:
    """尝试从存档复用图片到 output_path。返回是否成功。"""
    if archive_path is None or not archive_path.exists():
        return False
    try:
        shutil.copy2(archive_path, output_path)
        logger.info("Archive reuse: %s -> %s", archive_path.name, output_path)
        return True
    except Exception as e:
        logger.warning("Archive read failed %s: %s", archive_path, e)
        return False


def try_read_archive_bytes(archive_path: Path | None) -> bytes | None:
    """尝试从存档读取图片字节。返回 None 表示未命中或读取失败。"""
    if archive_path is None or not archive_path.exists():
        return None
    try:
        data = archive_path.read_bytes()
        logger.info("Archive reuse (bytes): %s (%d bytes)", archive_path.name, len(data))
        return data
    except Exception as e:
        logger.warning("Archive read bytes failed %s: %s", archive_path, e)
        return None


def write_archive(archive_path: Path | None, data: bytes) -> None:
    """把生成的图片字节落盘到存档，供下次复用。失败仅告警。"""
    if archive_path is None:
        return
    try:
        archive_path.write_bytes(data)
        logger.info("Archive written: %s", archive_path.name)
    except Exception as e:
        logger.warning("Archive write failed %s: %s", archive_path, e)
