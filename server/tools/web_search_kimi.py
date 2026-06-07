"""联网搜索工具 - 基于 Kimi $web_search 内置能力。

通过 Kimi API 的 builtin_function.$web_search 实现联网搜索，
搜索由 Kimi 服务端执行，无需自建搜索服务。

$web_search 协议流程（参考官方示例）：
1. 声明 builtin_function.$web_search 工具
2. Kimi 返回 tool_call（包含搜索参数）
3. 将 arguments 原封不动回传（json.loads -> json.dumps）
4. Kimi 服务端执行搜索，返回基于搜索结果的回答

注意：使用 $web_search 必须通过 extra_body 禁用思考模式。
"""

from __future__ import annotations

import json
import logging
import warnings

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def web_search_kimi(query: str) -> str:
    """联网搜索互联网获取最新信息。当用户的问题需要实时互联网数据、
    本地新闻库中没有相关信息时调用此工具。支持搜索任何话题的最新信息。
    返回基于搜索结果整理的摘要内容。"""
    from openai import AsyncOpenAI
    from config import MOONSHOT_API_KEY

    client = AsyncOpenAI(
        base_url="https://api.moonshot.cn/v1",
        api_key=MOONSHOT_API_KEY,
        timeout=30.0,
    )

    messages = [
        {"role": "system", "content": "你是 Kimi，擅长通过搜索互联网获取最新信息。请用中文回复。"},
        {"role": "user", "content": query},
    ]

    try:
        finish_reason = None
        while finish_reason is None or finish_reason == "tool_calls":
            logger.info("Web search (Kimi): calling Kimi API for query=%s", query)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Pydantic serializer warnings")
                response = await client.chat.completions.create(
                    model="kimi-k2.6",
                    messages=messages,
                    max_tokens=32768,
                    extra_body={"thinking": {"type": "disabled"}},
                    tools=[
                        {
                            "type": "builtin_function",
                            "function": {"name": "$web_search"},
                        }
                    ],
                )

            choice = response.choices[0]
            finish_reason = choice.finish_reason
            logger.info("Web search (Kimi): finish_reason=%s", finish_reason)

            if finish_reason == "tool_calls":
                # 将 Kimi 返回的 assistant 消息加入上下文
                messages.append(choice.message)
                for tool_call in choice.message.tool_calls:
                    tool_call_name = tool_call.function.name
                    tool_call_arguments = json.loads(tool_call.function.arguments)

                    if tool_call_name == "$web_search":
                        # $web_search 只需原封不动回传 arguments
                        tool_result = tool_call_arguments
                    else:
                        tool_result = f"Error: unable to find tool by name '{tool_call_name}'"

                    # 构造 role=tool 的消息，必须包含 tool_call_id 和 name
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call_name,
                        "content": json.dumps(tool_result),
                    })

        # 循环结束，返回最终回答
        result = choice.message.content or "搜索未返回结果。"
        logger.info("Web search (Kimi): got result, length=%d", len(result))
        return result

    except Exception as e:
        logger.exception("Web search via Kimi failed: %s", e)
        return f"联网搜索失败：{e}"
