"""Shared constants for all routers.

Small module holding HTTP/SSE headers and other cross-router constants,
kept separate from stateful modules so it can be imported anywhere
without pulling in heavy singletons.
"""

from __future__ import annotations

# ── SSE headers ───────────────────────────────────────────────────────
# 防止 Nginx 缓冲流式响应；所有 SSE 端点必须携带该 header。
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
