"""NewsInterpreter 测试（mock 模式，无需真实 LLM）。

覆盖 interpret/chat/generate_article 的 mock 路径、build_prompt_text、
astream_interpret/astream_chat 的流式分块。
"""

from __future__ import annotations

from core.interpreter import MOCK_RESPONSES, NewsInterpreter
from core.style_manager import StyleType


async def test_interpret_mock_returns_style_response():
    """mock 模式下 interpret 返回对应 style 的预设响应。"""
    interp = NewsInterpreter(mock=True)
    for style in (StyleType.XIAOHONGSHU, StyleType.WECHAT_MP, StyleType.DOUYIN):
        result = await interp.interpret([{"title": "t", "content": "c"}], style)
        assert result == MOCK_RESPONSES[style]


async def test_interpret_mock_unknown_style_falls_back_to_wechat():
    interp = NewsInterpreter(mock=True)
    result = await interp.interpret([{"title": "t"}], "wechat_mp")
    assert result == MOCK_RESPONSES[StyleType.WECHAT_MP]


async def test_chat_mock_returns_fixed_text():
    interp = NewsInterpreter(mock=True)
    result = await interp.chat("这是什么？", [{"title": "t", "content": "c"}])
    assert "这是什么？" in result
    assert "解读" in result


async def test_generate_article_mock_returns_dict_with_title_and_content():
    interp = NewsInterpreter(mock=True)
    news = [
        {"news_id": "n1", "title": "某重大新闻标题", "content": "内容"},
        {"news_id": "n2", "title": "另一条新闻", "content": "内容2"},
    ]
    article = await interp.generate_article(news, StyleType.WECHAT_MP)
    assert "title" in article
    assert "content" in article
    assert article["style"] == "wechat_mp"
    assert article["news_ids"] == ["n1", "n2"]
    assert "深度解读" in article["title"]


async def test_generate_article_xiaohongshu_title_format():
    interp = NewsInterpreter(mock=True)
    news = [{"news_id": "n1", "title": "一二三四五六七八九十十一", "content": "c"}]
    article = await interp.generate_article(news, StyleType.XIAOHONGSHU)
    assert "🌟" in article["title"]


async def test_generate_article_douyin_title_format():
    interp = NewsInterpreter(mock=True)
    news = [{"news_id": "n1", "title": "短标题", "content": "c"}]
    article = await interp.generate_article(news, StyleType.DOUYIN)
    assert "🔥" in article["title"]


async def test_generate_article_with_custom_title():
    interp = NewsInterpreter(mock=True)
    article = await interp.generate_article(
        [{"news_id": "n1", "title": "t", "content": "c"}],
        StyleType.WECHAT_MP,
        title="自定义标题",
    )
    assert article["title"] == "自定义标题"


async def test_generate_article_with_prompt_uses_generate_task():
    """带 prompt 时 interpret 走 generate task（mock 下仍返回 style 响应）。"""
    interp = NewsInterpreter(mock=True)
    article = await interp.generate_article(
        [{"news_id": "n1", "title": "t", "content": "c"}],
        StyleType.WECHAT_MP,
        prompt="写一篇分析",
    )
    assert article["content"] == MOCK_RESPONSES[StyleType.WECHAT_MP]


async def test_build_prompt_text_interpret_task():
    interp = NewsInterpreter(mock=True)
    text = interp.build_prompt_text([{"title": "标题", "content": "正文"}], StyleType.WECHAT_MP, task="interpret")
    assert "[System]" in text
    assert "[User]" in text
    assert "标题" in text
    assert "正文" in text


async def test_build_prompt_text_generate_task_with_prompt():
    interp = NewsInterpreter(mock=True)
    text = interp.build_prompt_text(
        [{"title": "标题", "content": "正文"}],
        StyleType.WECHAT_MP,
        prompt="用户自定义提示",
        task="generate",
    )
    assert "用户自定义提示" in text
    assert "正文" in text


async def test_build_prompt_text_chat_with_message():
    interp = NewsInterpreter(mock=True)
    text = interp.build_prompt_text(
        [{"title": "标题", "content": "正文"}],
        message="用户问题",
        task="chat",
    )
    assert "用户问题" in text
    assert "正文" in text


async def test_astream_interpret_yields_chunks():
    """astream_interpret mock 模式分块 yield，拼接后等于完整响应。"""
    interp = NewsInterpreter(mock=True)
    chunks = []
    async for chunk in interp.astream_interpret([{"title": "t", "content": "c"}], StyleType.DOUYIN):
        chunks.append(chunk)
    full = "".join(chunks)
    assert full == MOCK_RESPONSES[StyleType.DOUYIN]
    assert len(chunks) > 1  # 多块


async def test_astream_chat_yields_chunks():
    interp = NewsInterpreter(mock=True)
    chunks = [c async for c in interp.astream_chat("问题", [{"title": "t", "content": "c"}])]
    full = "".join(chunks)
    assert "问题" in full
    assert len(chunks) > 1


def test_news_text_helper_formats_news():
    from core.interpreter import _news_text

    text = _news_text([{"title": "标题A", "content": "内容A"}, {"title": "标题B", "content": "内容B"}])
    assert "标题：标题A" in text
    assert "内容：内容A" in text
    assert "标题：标题B" in text


def test_interpreter_init_mock_does_not_create_llm():
    """mock=True 时不创建 LLM 属性。"""
    interp = NewsInterpreter(mock=True)
    assert not hasattr(interp, "llm")
