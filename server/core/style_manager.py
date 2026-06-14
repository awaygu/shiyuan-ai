"""Prompt management for the news AI system.

Loads all prompts from prompts.py. Supports hot-reload via reload().
Provides per-task system prompts: interpret, generate (per style), chat.
"""

from __future__ import annotations

import importlib
import logging
from enum import Enum

import prompts as _prompts_module
from config import MAX_PROMPT_CHARS

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
        result = self._interpret_system
        if task == "interpret":
            result = self._interpret_system
        elif task == "generate":
            if style and style in self._generate_systems:
                result = self._generate_systems[style]
            else:
                result = self._generate_systems.get(StyleType.WECHAT_MP, "")
        elif task == "chat":
            result = self._chat_system

        # 长度保护：超过建议长度时告警
        max_len = MAX_PROMPT_CHARS.get(task)
        if max_len and len(result) > max_len:
            logger.warning(
                "Prompt for task=%s exceeds recommended length: %d > %d chars",
                task, len(result), max_len,
            )
        return result

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

    # ── New: direct access to migrated prompts ──────────────────────

    @property
    def version(self) -> str:
        return getattr(_prompts_module, "PROMPT_VERSION", "unknown")

    @property
    def updated_at(self) -> str:
        return getattr(_prompts_module, "PROMPT_UPDATED_AT", "")

    @property
    def kb_rag_system_prompt(self) -> str:
        return getattr(_prompts_module, "KB_RAG_SYSTEM_PROMPT", "")

    @property
    def kb_generate_system_prompt(self) -> str:
        return getattr(_prompts_module, "KB_GENERATE_SYSTEM_PROMPT", "")

    @property
    def rewrite_system_prompt(self) -> str:
        return getattr(_prompts_module, "REWRITE_SYSTEM_PROMPT", "")

    @property
    def agent_system_prompt(self) -> str:
        return getattr(_prompts_module, "AGENT_SYSTEM_PROMPT", "")

    @property
    def agent_role_prompt(self) -> str:
        return getattr(_prompts_module, "AGENT_ROLE_PROMPT", "")

    @property
    def agent_tools_overview(self) -> str:
        return getattr(_prompts_module, "AGENT_TOOLS_OVERVIEW", "")

    @property
    def agent_calling_rules(self) -> str:
        return getattr(_prompts_module, "AGENT_CALLING_RULES", "")

    @property
    def conversation_summary_prompt(self) -> str:
        return getattr(_prompts_module, "CONVERSATION_SUMMARY_PROMPT", "")

    @property
    def doc_summary_system_prompt(self) -> str:
        return getattr(_prompts_module, "DOC_SUMMARY_SYSTEM_PROMPT", "")

    @property
    def question_generator_system_prompt(self) -> str:
        return getattr(_prompts_module, "QUESTION_GENERATOR_SYSTEM_PROMPT", "")

    @property
    def title_generator_system_prompt(self) -> str:
        return getattr(_prompts_module, "TITLE_GENERATOR_SYSTEM_PROMPT", "")

    @property
    def image_prompt_writer_system_prompt(self) -> str:
        return getattr(_prompts_module, "IMAGE_PROMPT_WRITER_SYSTEM_PROMPT", "")

    @property
    def ocr_extraction_prompt(self) -> str:
        return getattr(_prompts_module, "OCR_EXTRACTION_PROMPT", "")

    @property
    def kimi_web_search_system_prompt(self) -> str:
        return getattr(_prompts_module, "KIMI_WEB_SEARCH_SYSTEM_PROMPT", "")

    @property
    def kb_style_hints(self) -> dict[str, str]:
        return getattr(_prompts_module, "KB_STYLE_HINTS", {})


prompt_manager = PromptManager()
