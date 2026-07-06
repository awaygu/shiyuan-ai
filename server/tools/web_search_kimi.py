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

from core.style_manager import prompt_manager

logger = logging.getLogger(__name__)


@tool
async def web_search_kimi(query: str) -> str:
    """联网搜索互联网获取最新信息。当用户的问题需要实时互联网数据、
    本地新闻库中没有相关信息时调用此工具。支持搜索任何话题的最新信息。
    返回基于搜索结果整理的摘要内容。"""
    from openai import AsyncOpenAI

    from config import MOONSHOT_API_KEY

    # Kimi $web_search 由服务端先搜索再生成，整体耗时较长；
    # 单次 chat 请求设 120s，并允许最多 2 次重试，覆盖偶发超时。
    client = AsyncOpenAI(
        base_url="https://api.moonshot.cn/v1",
        api_key=MOONSHOT_API_KEY,
        timeout=120.0,
        max_retries=2,
    )

    messages = [
        {"role": "system", "content": prompt_manager.kimi_web_search_system_prompt},
        {"role": "user", "content": query},
    ]

    # 防御：tool_calls 循环最多走 5 轮，避免异常情况下死循环。
    max_rounds = 5
    finish_reason = None
    choice = None
    rounds = 0

    try:
        while (finish_reason is None or finish_reason == "tool_calls") and rounds < max_rounds:
            rounds += 1
            logger.info("Web search (Kimi): calling Kimi API for query=%s (round %d)", query, rounds)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Pydantic serializer warnings")
                response = await client.chat.completions.create(
                    model="kimi-k2.6",
                    messages=messages,
                    max_tokens=4096,
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
            logger.info("Web search (Kimi): finish_reason=%s (round %d)", finish_reason, rounds)

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
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call_name,
                            "content": json.dumps(tool_result),
                        }
                    )

        if rounds >= max_rounds and finish_reason == "tool_calls":
            # 触发 tool_calls 循环上限，视为失败而非静默返回空
            raise RuntimeError("Kimi $web_search 轮次超限，可能服务端未返回最终回答")

        # 循环结束，返回最终回答
        result = (choice.message.content if choice else "") or "搜索未返回结果。"
        logger.info("Web search (Kimi): got result, length=%d (rounds=%d)", len(result), rounds)
        return result

    except Exception as e:
        logger.exception("Web search via Kimi failed: %s", e)
        # 不再吞成“成功文本”，直接抛出，由上层 web_search_structured /
        # kb_web_search 捕获并返回 500，让前端看到真实失败原因。
        raise
