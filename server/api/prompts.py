"""Prompt management API routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.style_manager import prompt_manager

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("/status")
async def get_prompts_status():
    return {
        "version": prompt_manager.version,
        "updated_at": prompt_manager.updated_at,
        "interpret_system_length": len(prompt_manager.get_system_prompt("interpret")),
        "chat_system_length": len(prompt_manager.get_system_prompt("chat")),
        "generate_styles": {
            s.value: len(prompt_manager.get_system_prompt("generate", s))
            for s in prompt_manager.available_styles
        },
        "styles": [s.value for s in prompt_manager.available_styles],
        "has_chat_template": bool(prompt_manager.chat_template),
        "has_generate_user_prompt_template": bool(prompt_manager.generate_with_user_prompt_template),
    }


@router.post("/reload")
async def reload_prompts():
    prompt_manager.load()
    return {
        "version": prompt_manager.version,
        "updated_at": prompt_manager.updated_at,
        "interpret_system_length": len(prompt_manager.get_system_prompt("interpret")),
        "chat_system_length": len(prompt_manager.get_system_prompt("chat")),
        "generate_styles": {
            s.value: len(prompt_manager.get_system_prompt("generate", s))
            for s in prompt_manager.available_styles
        },
        "styles": [s.value for s in prompt_manager.available_styles],
    }
