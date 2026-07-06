"""Keyword filter management API routes."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import KEYWORDS_FILE
from sources.filter import KeywordFilter

from . import deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/keywords", tags=["keywords"])


@router.get("/status")
async def get_keywords_status():
    total_rules = sum(len(rules) for rules in deps.kw_filter.groups.values())
    return {
        "enabled": deps.kw_filter.enabled,
        "file": KEYWORDS_FILE,
        "groups": [
            {"name": name, "keywords": [kw for kw, _ in rules]} for name, rules in deps.kw_filter.groups.items()
        ],
        "total_rules": total_rules,
    }


@router.post("/reload")
async def reload_keywords():
    deps.kw_filter = KeywordFilter(KEYWORDS_FILE)
    total_rules = sum(len(rules) for rules in deps.kw_filter.groups.values())
    return {
        "enabled": deps.kw_filter.enabled,
        "total_rules": total_rules,
        "groups": list(deps.kw_filter.groups.keys()),
    }


class KeywordGroup(BaseModel):
    name: str
    keywords: list[str]


class UpdateKeywordsRequest(BaseModel):
    groups: list[KeywordGroup]


HEADER_LINES = [
    "# 关键词过滤配置",
    "# 语法说明：",
    "#   - # 开头的行为分组名（也是标签名）",
    "#   - /regex/ 为正则匹配（斜杠包裹）",
    "#   - 其他文本为包含匹配（标题或摘要中出现即命中）",
    "#   - 空行和 // 开头的行被忽略",
    "#   - 多组规则之间为 OR 关系，命中任意一条即保留该新闻",
    "#   - 文件不存在或为空时，不过滤，全部保留",
    "",
]

_KEYWORDS_PATH = Path(KEYWORDS_FILE)


@router.put("")
async def update_keywords(req: UpdateKeywordsRequest):
    try:
        lines = list(HEADER_LINES)
        for group in req.groups:
            lines.append(f"# {group.name}")
            for kw in group.keywords:
                lines.append(kw)
            lines.append("")
        await asyncio.to_thread(_KEYWORDS_PATH.write_text, "\n".join(lines), encoding="utf-8")
    except Exception as e:
        logger.error("Failed to write keywords file: %s", e)
        raise HTTPException(500, f"Failed to write keywords file: {e}")

    deps.kw_filter = KeywordFilter(KEYWORDS_FILE)
    total_rules = sum(len(rules) for rules in deps.kw_filter.groups.values())
    return {
        "enabled": deps.kw_filter.enabled,
        "total_rules": total_rules,
        "groups": [
            {"name": name, "keywords": [kw for kw, _ in rules]} for name, rules in deps.kw_filter.groups.items()
        ],
    }
