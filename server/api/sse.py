"""SSE error 事件统一 helper。

收拢各 SSE 端点里重复的 ``yield f"data: {json.dumps({'type':'error',
'message': ...})}\n\n"`` 模式，统一 error 事件字段（仅 ``message``，前端
``web/src/api/index.ts`` 只读 ``parsed.message``）。

加可选 ``code`` 字段（非破坏性，前端不读，仅扩展用），供后续按错误码分类。

注意：SSE 端点内异常不走全局 exception_handler（在 ``event_stream()``
内部 catch），故需要本 helper 显式发 error 事件。
"""

from __future__ import annotations

import json


def sse_error(message: str, code: int | None = None) -> str:
    """构造 SSE error 事件行（含末尾 ``\\n\\n`` 分隔）。

    返回 ``"data: " + json.dumps({...}, ensure_ascii=False) + "\\n\\n"``。
    字段 ``type`` 固定 ``"error"``，``message`` 为人类可读错误文本，``code``
    可选（前端不读，仅扩展用）。

    用法::

        except Exception as e:
            yield sse_error(f"处理失败：{e}")
    """
    payload: dict = {"type": "error", "message": message}
    if code is not None:
        payload["code"] = code
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
