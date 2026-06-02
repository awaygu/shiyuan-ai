"""Prompt management for the news AI system.

Loads all prompts from prompts.py. Supports hot-reload via reload().
Provides per-task system prompts: interpret, generate (per style), chat.
"""

from __future__ import annotations

import importlib
import logging
from enum import Enum

import prompts as _prompts_module

logger = logging.getLogger(__name__)


class StyleType(str, Enum):
    XIAOHONGSHU = "xiaohongshu"
    WECHAT_MP = "wechat_mp"
    DOUYIN = "douyin"


class PromptManager:
    """Central prompt manager. Loads from prompts.py and provides typed access."""

    def __init__(self):
        self._interpret_system: str = ""
        self._generate_systems: dict[StyleType, str] = {}
        self._chat_system: str = ""
        self._interpret_human: str = ""
        self._generate_human: str = ""
        self._generate_with_user_prompt: str = ""
        self.chat_template: str = ""
        self.load()

    def load(self) -> None:
        importlib.reload(_prompts_module)

        self._interpret_system = _prompts_module.SYSTEM_INTERPRET
        self._generate_systems = {
            StyleType(k): v
            for k, v in _prompts_module.SYSTEM_GENERATE.items()
            if k in [e.value for e in StyleType]
        }
        self._chat_system = _prompts_module.SYSTEM_CHAT

        self._interpret_human = _prompts_module.INTERPRET_HUMAN
        self._generate_human = _prompts_module.GENERATE_HUMAN
        self._generate_with_user_prompt = _prompts_module.GENERATE_WITH_USER_PROMPT
        self.chat_template = _prompts_module.CHAT

        logger.info(
            "Loaded prompts: %d generate styles, interpret=%d chars, chat=%d chars",
            len(self._generate_systems),
            len(self._interpret_system),
            len(self._chat_system),
        )

    def get_system_prompt(self, task: str, style: StyleType | None = None) -> str:
        if task == "interpret":
            return self._interpret_system
        elif task == "generate":
            if style and style in self._generate_systems:
                return self._generate_systems[style]
            return self._generate_systems.get(StyleType.WECHAT_MP, "")
        elif task == "chat":
            return self._chat_system
        return self._interpret_system

    def get_interpret_human(self) -> str:
        return self._interpret_human

    def get_generate_human(self) -> str:
        return self._generate_human

    @property
    def generate_with_user_prompt_template(self) -> str:
        return self._generate_with_user_prompt

    def get_style_prompt(self, style: StyleType) -> str:
        return self._generate_systems.get(style, self._generate_systems.get(StyleType.WECHAT_MP, ""))

    @property
    def available_styles(self) -> list[StyleType]:
        return list(self._generate_systems.keys())


prompt_manager = PromptManager()
