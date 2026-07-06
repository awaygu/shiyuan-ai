"""Conversations API — 对话管理端点。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.checkpointer import (
    clear_messages,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_messages,
    list_conversations,
    update_conversation_title,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conversations", tags=["conversations"])


# ── Request/Response Models ────────────────────────────────────


class CreateConversationRequest(BaseModel):
    title: str = "新对话"


class UpdateTitleRequest(BaseModel):
    title: str


# ── Endpoints ──────────────────────────────────────────────────


@router.post("")
async def api_create_conversation(req: CreateConversationRequest | None = None):
    """创建新对话。"""
    title = req.title if req else "新对话"
    conv = create_conversation(title=title)
    return conv


@router.get("")
async def api_list_conversations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """获取对话列表。"""
    return list_conversations(limit=limit, offset=offset)


@router.get("/{conv_id}")
async def api_get_conversation(conv_id: str):
    """获取单个对话信息。"""
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    return conv


@router.delete("/{conv_id}")
async def api_delete_conversation(conv_id: str):
    """软删除对话。"""
    ok = delete_conversation(conv_id)
    if not ok:
        raise HTTPException(404, "对话不存在")
    return {"success": True}


@router.patch("/{conv_id}")
async def api_update_conversation(conv_id: str, req: UpdateTitleRequest):
    """更新对话标题。"""
    ok = update_conversation_title(conv_id, req.title)
    if not ok:
        raise HTTPException(404, "对话不存在")
    return {"success": True}


@router.get("/{conv_id}/messages")
async def api_get_messages(conv_id: str):
    """获取对话历史消息。"""
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    msgs = get_messages(conv_id)
    return {"conversation_id": conv_id, "messages": msgs}


@router.delete("/{conv_id}/messages")
async def api_clear_messages(conv_id: str):
    """清空对话消息。"""
    count = clear_messages(conv_id)
    return {"success": True, "deleted_count": count}
