"""AI interpreter, publishers, keyword filter, and style resolver.

Holds the process-wide singletons that routers share: the ``NewsInterpreter``
instance, the publisher dict, the keyword filter, plus the ``resolve_style``
helper used by the interpret / agent / generate endpoints.

``publish.py`` reassigns ``deps.PUBLISHERS`` at import time (to inject
real WeChat credentials) and ``keywords.py`` reassigns
``deps.kw_filter`` on reload; both writes go through ``deps`` so every
reader stays consistent.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from config import KEYWORDS_FILE, KEYWORDS_FILTER_ENABLED
from core import NewsInterpreter, StyleType
from publishers import DouyinPublisher, WechatMpPublisher, XiaohongshuPublisher
from sources.filter import KeywordFilter

# ── AI interpreter ────────────────────────────────────────────────────
# 全局唯一的解读/生成器实例，mock=False 表示使用真实 LLM。
interpreter = NewsInterpreter(mock=False)

# ── Publishers ────────────────────────────────────────────────────────
# 初始化默认发布器；publish.py 在导入时会用真实微信凭证覆盖 wechat_mp 项。
PUBLISHERS: dict[str, Any] = {
    "xiaohongshu": XiaohongshuPublisher(),
    "wechat_mp": WechatMpPublisher(),
    "douyin": DouyinPublisher(),
}

# ── Keyword filter ────────────────────────────────────────────────────
# 关键词过滤器：未启用过滤时传 None（KeywordFilter 内部视为直通）。
kw_filter = KeywordFilter(KEYWORDS_FILE if KEYWORDS_FILTER_ENABLED else None)

# ── Style resolver ────────────────────────────────────────────────────


def resolve_style(style_str: str) -> StyleType:
    """将字符串风格名解析为 StyleType 枚举，非法值返回 400。"""
    try:
        return StyleType(style_str)
    except ValueError:
        raise HTTPException(
            400,
            f"Invalid style: {style_str}. Choose from: {[e.value for e in StyleType]}",
        )
