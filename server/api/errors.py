"""统一错误处理：HTTPException helper + 全局 exception_handler。

本模块收拢两件事：

1. **HTTPException helper**：收拢路由里高频重复的 ``raise HTTPException(...)``
   模式（404 not found / 400 bad request / 500 server error / 400 unknown
   platform）。helper 的主要价值是给全局 handler 一个统一的错误来源，同时
   减少散落的字面量。改造遵循"改动面控制"原则：helper 建好后替换
   ``knowledge.py`` 中高频重复的 "Knowledge base not found" 等点，其余
   路由保持现状，避免大规模 churn 出错。

2. **全局 exception_handler**：在 ``app.py`` 注册三类 handler，统一普通
   JSON 端点的错误响应格式。**注意**：lifespan 内异常与 SSE 端点内异常
   不走全局 handler（前者在请求级 handler 之外，后者在 ``event_stream()``
   内部 catch），全局 handler 只覆盖普通 JSON 端点。

统一 envelope（非破坏性，保留前端能读的 ``detail`` 字段）::

    {"detail": <str|list>, "code": <int status>, "type": <str>}

保留 ``detail`` 是为了向后兼容——FastAPI 默认 HTTPException 返回
``{"detail": msg}``，且后端测试 ``test_interpret.py`` 直接断言
``resp.json()["detail"]``。``code`` / ``type`` 为新增扩展字段，前端只读
SSE 的 ``message``、HTTP 错误只取 ``e.message``，新增字段不破坏前端。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 错误类型标签，随响应体返回，便于前端/日志分类（前端目前不读，仅扩展用）。
TYPE_HTTP_ERROR = "http_error"
TYPE_VALIDATION_ERROR = "validation_error"
TYPE_SERVER_ERROR = "server_error"


# ── HTTPException helper ───────────────────────────────────────


def not_found(msg: str = "Not found") -> None:
    """抛 404 HTTPException。收拢 ``raise HTTPException(404, msg)`` 重复模式。"""
    raise HTTPException(status_code=404, detail=msg)


def bad_request(msg: str) -> None:
    """抛 400 HTTPException。收拢 ``raise HTTPException(400, msg)`` 重复模式。"""
    raise HTTPException(status_code=400, detail=msg)


def server_error(prefix: str, e: Exception) -> None:
    """抛 500 HTTPException，detail 形如 ``f"{prefix}: {e}"``。

    收拢 ``raise HTTPException(500, f"Embedding failed: {e}")`` 等重复模式。
    调用方通常已自行 ``logger.exception``，此处不再重复打 log。
    """
    raise HTTPException(status_code=500, detail=f"{prefix}: {e}")


def unknown_platform(platform: str, available: list[str] | None = None) -> None:
    """抛 400，提示未知发布平台及可选的可用列表。"""
    avail_hint = f". Available: {', '.join(available)}" if available else ""
    raise HTTPException(status_code=400, detail=f"Unknown platform: {platform}{avail_hint}")


# ── 统一 envelope 构造 ─────────────────────────────────────────


def _envelope(detail, code: int, type_: str) -> dict:
    """构造统一错误响应体，保留 ``detail`` 兼容字段 + ``code``/``type`` 扩展。"""
    return {"detail": detail, "code": code, "type": type_}


# ── 全局 exception_handler 注册 ────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:
    """注册三类全局 exception_handler，统一普通 JSON 端点的错误响应格式。

    在 ``app`` 创建后、middleware 前调用（见 ``app.py``）。
    """

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        # 标准化为统一 envelope：保留 detail 兼容，补 code/type 扩展字段。
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.detail, exc.status_code, TYPE_HTTP_ERROR),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError):
        # 422 参数校验错误统一格式，detail 保留 FastAPI 原始的 errors 列表。
        return JSONResponse(
            status_code=422,
            content=_envelope(exc.errors(), 422, TYPE_VALIDATION_ERROR),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        # 兜底 500：记完整 trace，返回结构化 detail（不向客户端泄露内部异常文本）。
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_envelope("Internal server error", 500, TYPE_SERVER_ERROR),
        )
