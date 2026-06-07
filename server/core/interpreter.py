"""AI news interpreter using LangChain.

Supports both non-streaming and streaming (SSE) output.
All prompts are managed via PromptManager (loaded from prompts.py).
Each task (interpret, generate, chat) uses its own system prompt.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .style_manager import StyleType, prompt_manager

MOCK_RESPONSES: dict[StyleType, str] = {
    StyleType.XIAOHONGSHU: (
        "姐妹们！！这个新闻真的绝了 🤯\n\n"
        "💥 **重点划好了** 赶紧来看！\n"
        "这个事儿真的跟咱们每个人都息息相关，不关注就亏大了～\n\n"
        "📌 先说说背景：其实这个事情已经酝酿很久了，最近终于有了实质性进展。\n"
        "很多人可能觉得跟自己没啥关系，但其实影响比你想象的大多了！\n\n"
        "🔍 我研究了一下，给大家总结几个关键point：\n"
        "1️⃣ 第一个点：这个变化会直接影响到...\n"
        "2️⃣ 第二个点：对普通人来说，这是好事还是坏事？\n"
        "3️⃣ 第三个点：接下来怎么应对，我的建议是...\n\n"
        "💡 我个人觉得啊，这个趋势是挡不住的，与其焦虑不如早点做准备～\n"
        "真的建议大家多关注这方面的信息，越早了解越主动！\n\n"
        "好啦今天的分享就到这里～姐妹们觉得有用的话点个❤️收藏哦！\n\n"
        "#热点解读 #财经干货 #必须要知道的事"
    ),
    StyleType.WECHAT_MP: (
        "## 深度解读：这件事的影响远比你想的更深远\n\n"
        "### 一、事件回顾\n"
        "最近这条新闻引发了广泛关注。表面上看只是一个普通消息，但深入分析后会发现，"
        "其背后蕴含的信号值得每一个人重视。\n\n"
        "### 二、核心影响分析\n"
        "从多个维度来看，这个事件带来的影响可以分为三个层面：\n\n"
        "**1. 对行业的影响**\n"
        "行业生态正在发生深刻变革。数据显示，相关领域的市场规模在过去一年增长了约30%，"
        "参与企业数量增加了50%以上。这意味着竞争格局正在重塑。\n\n"
        "**2. 对个人的影响**\n"
        "对普通用户来说，这既是机遇也是挑战。一方面可以获得更好的服务和体验，"
        "另一方面也需要面对变化带来的不确定性。\n\n"
        "**3. 对宏观经济的影响**\n"
        "从宏观视角看，这一变化符合国家产业升级的大方向，有助于提升整体竞争力。\n\n"
        "### 三、未来展望\n"
        "展望未来，我们认为这一趋势会持续加速。建议读者朋友们从以下三个方面做好准备：\n"
        "第一，保持信息敏感度，及时了解最新动态……"
    ),
    StyleType.DOUYIN: (
        "🔥 这条消息你敢信？！\n"
        "不看的真的亏大了！\n\n"
        "听我说！3个重点！👇\n\n"
        "第一！这件事跟每个人有关！\n"
        "第二！变化比你想的快得多！\n"
        "第三！现在知道还不晚！\n\n"
        "你觉得呢？评论区告诉我！\n"
        "点赞关注，下期更精彩！🚀"
    ),
}


def _news_text(news_list: list[dict]) -> str:
    return "\n\n".join(
        f"标题：{n.get('title', '')}\n内容：{n.get('content', '')}"
        for n in news_list
    )


class NewsInterpreter:
    """AI news interpreter.

    In mock mode returns predefined responses per style.
    In real mode uses LangChain + OpenAI-compatible LLM.
    Each task uses its own system prompt via PromptManager.
    """

    def __init__(self, mock: bool = True):
        self.mock = mock
        self.pm = prompt_manager
        if not mock:
            self.llm = ChatOpenAI(
                model=LLM_MODEL,
                temperature=0.7,
                streaming=True,
                api_key=LLM_API_KEY,
                base_url=LLM_BASE_URL,
                timeout=120,
                max_retries=2,
                extra_body={"enable_thinking": False},
            )

    def _build_human_message(
        self,
        task: str,
        news_list: list[dict],
        style: StyleType = StyleType.WECHAT_MP,
        prompt: str | None = None,
    ) -> str:
        news = _news_text(news_list)
        if task == "interpret":
            return self.pm.get_interpret_human().format(news_text=news)
        elif task == "generate":
            if prompt:
                return self.pm.generate_with_user_prompt_template.format(
                    user_prompt=prompt, news_text=news,
                )
            return self.pm.get_generate_human().format(news_text=news)
        return news

    def build_prompt_text(
        self,
        news_list: list[dict],
        style: StyleType = StyleType.WECHAT_MP,
        prompt: str | None = None,
        message: str | None = None,
        task: str = "interpret",
    ) -> str:
        """Build and return the full prompt text (system + human) for display."""
        system = self.pm.get_system_prompt(task, style)
        if message:
            news = _news_text(news_list)
            human = self.pm.chat_template.format(message=message, news_text=news)
        else:
            human = self._build_human_message(task, news_list, style, prompt)
        return f"[System]\n{system}\n\n[User]\n{human}"

    async def interpret(
        self,
        news_list: list[dict],
        style: StyleType = StyleType.WECHAT_MP,
        prompt: str | None = None,
    ) -> str:
        """Generate AI interpretation of given news items."""
        if self.mock:
            return MOCK_RESPONSES.get(style, MOCK_RESPONSES[StyleType.WECHAT_MP])

        task = "generate" if prompt else "interpret"
        system = self.pm.get_system_prompt(task, style)
        human = self._build_human_message(task, news_list, style, prompt)
        prompt_text = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", human),
        ])
        chain = prompt_text | self.llm
        result = await chain.ainvoke({})
        return result.content

    async def chat(
        self,
        message: str,
        news_list: list[dict],
    ) -> str:
        """Chat-style interpretation."""
        if self.mock:
            return (
                f"好的，我来为你解读这个问题。\n\n"
                f"你问的是：「{message}」\n\n"
                f"结合你提供的相关资讯，我的分析如下：\n\n"
                f"1️⃣ 首先，从这些信息来看，核心变化在于行业格局正在重塑。\n"
                f"   多家企业都在积极布局，竞争越来越激烈。\n\n"
                f"2️⃣ 其次，对普通用户来说，这意味着选择更多了，\n"
                f"   但同时也需要更加理性地做出判断。\n\n"
                f"3️⃣ 最后，我建议你可以重点关注头部玩家的动向，\n"
                f"   以及政策面的最新变化。\n\n"
                f"希望这个分析对你有帮助！还有什么想了解的吗？"
            )

        system = self.pm.get_system_prompt("chat")
        news = _news_text(news_list)
        human = self.pm.chat_template.format(message=message, news_text=news)
        prompt_text = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", human),
        ])
        chain = prompt_text | self.llm
        result = await chain.ainvoke({})
        return result.content

    async def generate_article(
        self,
        news_list: list[dict],
        style: StyleType = StyleType.WECHAT_MP,
        title: str | None = None,
        prompt: str | None = None,
    ) -> dict:
        """Generate a complete article from news items."""
        content = await self.interpret(news_list, style, prompt)

        if not title:
            if style == StyleType.XIAOHONGSHU:
                title = f"🌟 {' & '.join(n.get('title', '')[:20] for n in news_list[:2])} 深度解读"
            elif style == StyleType.DOUYIN:
                title = f"🔥 {' '.join(n.get('title', '')[:15] for n in news_list[:2])}"
            else:
                title = f"深度解读 | {' · '.join(n.get('title', '')[:15] for n in news_list[:2])}"

        return {
            "title": title,
            "content": content,
            "style": style.value,
            "news_ids": [n.get("news_id") for n in news_list],
        }

    async def astream_interpret(
        self,
        news_list: list[dict],
        style: StyleType = StyleType.WECHAT_MP,
        prompt: str | None = None,
        task: str = "interpret",
    ) -> AsyncGenerator[str, None]:
        """Streaming version of interpret. Yields text chunks."""
        if self.mock:
            full = MOCK_RESPONSES.get(style, MOCK_RESPONSES[StyleType.WECHAT_MP])
            chunk_size = 4
            for i in range(0, len(full), chunk_size):
                yield full[i:i + chunk_size]
                await asyncio.sleep(0.02)
            return

        system = self.pm.get_system_prompt(task, style)
        human = self._build_human_message(task, news_list, style, prompt)
        prompt_text = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", human),
        ])
        chain = prompt_text | self.llm
        async for chunk in chain.astream({}):
            if chunk.content:
                yield chunk.content

    async def astream_chat(
        self,
        message: str,
        news_list: list[dict],
    ) -> AsyncGenerator[str, None]:
        """Streaming version of chat. Yields text chunks."""
        if self.mock:
            full = (
                f"好的，我来为你解读这个问题。\n\n"
                f"你问的是：「{message}」\n\n"
                f"结合你提供的相关资讯，我的分析如下：\n\n"
                f"1️⃣ 首先，从这些信息来看，核心变化在于行业格局正在重塑。\n"
                f"   多家企业都在积极布局，竞争越来越激烈。\n\n"
                f"2️⃣ 其次，对普通用户来说，这意味着选择更多了，\n"
                f"   但同时也需要更加理性地做出判断。\n\n"
                f"3️⃣ 最后，我建议你可以重点关注头部玩家的动向，\n"
                f"   以及政策面的最新变化。\n\n"
                f"希望这个分析对你有帮助！还有什么想了解的吗？"
            )
            chunk_size = 4
            for i in range(0, len(full), chunk_size):
                yield full[i:i + chunk_size]
                await asyncio.sleep(0.02)
            return

        system = self.pm.get_system_prompt("chat")
        news = _news_text(news_list)
        human = self.pm.chat_template.format(message=message, news_text=news)
        prompt_text = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", human),
        ])
        chain = prompt_text | self.llm
        async for chunk in chain.astream({}):
            if chunk.content:
                yield chunk.content
