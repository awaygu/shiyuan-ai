"""api/content.py 测试：纯函数 + ensure_content 抓取（mock httpx，离线）。

覆盖 _clean_jina_content / is_limited_content / _ensure_limited_content /
_extract_meta_description / ensure_content 各分支。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from api import content

# ── _clean_jina_content ──


def test_clean_jina_content_strips_headers():
    text = "Title: 某标题\nURL Source: https://x.com\nMarkdown Content:\n正文内容。"
    _clean = content._clean_jina_content(text)
    assert "Title:" not in _clean
    assert "URL Source:" not in _clean
    assert "Markdown Content:" not in _clean
    assert "正文内容" in _clean


def test_clean_jina_content_removes_backtick_urls():
    text = "正文开始\n`https://example.com/page`\n继续正文。"
    cleaned = content._clean_jina_content(text)
    assert "`https://example.com/page`" not in cleaned
    assert "继续正文" in cleaned


def test_clean_jina_content_removes_markdown_image_links():
    text = "内容前 !`https://img.com/a.png` 内容后"
    cleaned = content._clean_jina_content(text)
    assert "img.com" not in cleaned


def test_clean_jina_content_collapses_blank_lines():
    text = "段一\n\n\n\n\n段二"
    cleaned = content._clean_jina_content(text)
    assert "\n\n\n" not in cleaned


# ── is_limited_content / _ensure_limited_content ──


def test_is_limited_content_true_for_limited_marker():
    item = {"content": "[全文需在浏览器中查看]\n标题：x"}
    assert content.is_limited_content(item) is True


def test_is_limited_content_false_for_normal():
    assert content.is_limited_content({"content": "正常正文内容"}) is False


def test_is_limited_content_false_for_empty():
    assert content.is_limited_content({}) is False
    assert content.is_limited_content({"content": ""}) is False


def test_ensure_limited_content_builds_marker_text():
    item = {"summary": "摘要", "title": "标题"}
    content._ensure_limited_content(item)
    assert item["content"].startswith("[全文需在浏览器中查看]")
    assert "标题：标题" in item["content"]
    assert "摘要：摘要" in item["content"]


def test_ensure_limited_content_skips_summary_when_equal_title():
    item = {"summary": "标题", "title": "标题"}
    content._ensure_limited_content(item)
    assert "摘要" not in item["content"]


def test_ensure_limited_content_handles_missing_fields():
    item = {}
    content._ensure_limited_content(item)
    assert "[全文需在浏览器中查看]" in item["content"]


# ── ensure_content ──


async def test_ensure_content_skips_when_existing_content_present():
    """已有正文（与 summary 不同）时直接返回，不抓取。"""
    item = {"content": "完整正文", "summary": "摘要", "news_id": "n1", "url": "https://x.com"}
    with patch("api.content.update_news_content", new=AsyncMock()) as mock_update:
        await content.ensure_content(item)
    mock_update.assert_not_called()
    assert item["content"] == "完整正文"


async def test_ensure_content_no_url_returns_without_fetch():
    """无 url 时直接返回，不修改 content。"""
    item = {"content": "", "summary": "s", "news_id": "n1", "url": "", "source": "cls-hot"}
    await content.ensure_content(item)
    assert item["content"] == ""


async def test_ensure_content_js_rendered_source_uses_jina(monkeypatch):
    """JS 渲染源走 Jina，抓到内容则落库并更新缓存。"""
    item = {
        "content": "",
        "summary": "s",
        "news_id": "n1",
        "url": "https://toutiao.com/x",
        "source": "toutiao",
        "extra": {"media_type": "article"},
    }

    async def _fake_jina(url):
        assert url == "https://toutiao.com/x"
        return "Jina 抓取的正文内容，长度足够超过阈值。"

    async def _fake_fetch(url):
        return "不应走普通抓取"

    monkeypatch.setattr(content, "fetch_article_content_via_jina", _fake_jina)
    monkeypatch.setattr(content, "fetch_article_content", _fake_fetch)

    updated = []

    async def _fake_update(nid, c):
        updated.append((nid, c))

    monkeypatch.setattr(content, "update_news_content", _fake_update)

    await content.ensure_content(item)
    assert item["content"] == "Jina 抓取的正文内容，长度足够超过阈值。"
    assert updated == [("n1", "Jina 抓取的正文内容，长度足够超过阈值。")]


async def test_ensure_content_js_rendered_jina_empty_falls_back_to_limited(monkeypatch):
    """JS 渲染源 Jina 抓不到时回退到 limited content。"""
    item = {
        "content": "",
        "summary": "s",
        "news_id": "n1",
        "url": "https://toutiao.com/x",
        "source": "toutiao",
        "extra": {"media_type": "article"},
    }
    monkeypatch.setattr(content, "fetch_article_content_via_jina", AsyncMock(return_value=""))
    monkeypatch.setattr(content, "update_news_content", AsyncMock())
    await content.ensure_content(item)
    assert item["content"].startswith("[全文需在浏览器中查看]")


async def test_ensure_content_normal_source_fetch_success(monkeypatch):
    """普通源直接抓取成功：落库 + 更新缓存。"""
    item = {
        "content": "",
        "summary": "s",
        "news_id": "n1",
        "url": "https://cls.com/x",
        "source": "cls-hot",
        "extra": {"media_type": "article"},
    }

    async def _fake_fetch(url):
        return "普通抓取的正文，长度足够。"

    monkeypatch.setattr(content, "fetch_article_content", _fake_fetch)
    updated = []

    async def _fake_update(nid, c):
        updated.append((nid, c))

    monkeypatch.setattr(content, "update_news_content", _fake_update)
    await content.ensure_content(item)
    assert item["content"] == "普通抓取的正文，长度足够。"
    assert updated == [("n1", "普通抓取的正文，长度足够。")]


async def test_ensure_content_normal_source_fetch_empty_then_jina(monkeypatch):
    """普通源抓取失败时回退 Jina，Jina 成功则用 Jina 结果。"""
    item = {
        "content": "",
        "summary": "s",
        "news_id": "n1",
        "url": "https://cls.com/x",
        "source": "cls-hot",
        "extra": {"media_type": "article"},
    }
    monkeypatch.setattr(content, "fetch_article_content", AsyncMock(return_value=""))
    monkeypatch.setattr(content, "fetch_article_content_via_jina", AsyncMock(return_value="Jina 回退正文，长度足够。"))
    monkeypatch.setattr(content, "update_news_content", AsyncMock())
    await content.ensure_content(item)
    assert item["content"] == "Jina 回退正文，长度足够。"


async def test_ensure_content_all_fetch_empty_falls_back_to_limited(monkeypatch):
    """普通源 + Jina 都抓不到时回退 limited content。"""
    item = {
        "content": "",
        "summary": "s",
        "news_id": "n1",
        "url": "https://cls.com/x",
        "source": "cls-hot",
        "extra": {"media_type": "article"},
    }
    monkeypatch.setattr(content, "fetch_article_content", AsyncMock(return_value=""))
    monkeypatch.setattr(content, "fetch_article_content_via_jina", AsyncMock(return_value=""))
    monkeypatch.setattr(content, "update_news_content", AsyncMock())
    await content.ensure_content(item)
    assert item["content"].startswith("[全文需在浏览器中查看]")


async def test_ensure_content_video_uses_video_path(monkeypatch):
    """media_type=video 走 _ensure_video_content。"""
    item = {
        "content": "",
        "summary": "视频摘要",
        "news_id": "n1",
        "url": "https://douyin.com/v/1",
        "source": "douyin",
        "extra": {"media_type": "video"},
    }
    called = []

    async def _fake_video_metadata(url):
        called.append(url)
        return {"description": "视频简介", "tags": ["标签1"], "author": "作者", "stats": "时长: 30s"}

    monkeypatch.setattr(content, "_extract_video_metadata", _fake_video_metadata)
    updated = []

    async def _fake_update(nid, c):
        updated.append((nid, c))

    monkeypatch.setattr(content, "update_news_content", _fake_update)
    await content.ensure_content(item)
    assert called == ["https://douyin.com/v/1"]
    assert "视频简介" in item["content"]
    assert "标签1" in item["content"]
    assert updated  # 已落库


async def test_ensure_content_video_no_metadata_uses_summary(monkeypatch):
    """video 源抓不到元数据时回退用 summary。"""
    item = {
        "content": "",
        "summary": "视频摘要",
        "news_id": "n1",
        "url": "https://douyin.com/v/1",
        "source": "douyin",
        "extra": {"media_type": "video"},
    }
    monkeypatch.setattr(content, "_extract_video_metadata", AsyncMock(return_value=None))
    monkeypatch.setattr(content, "update_news_content", AsyncMock())
    await content.ensure_content(item)
    assert item["content"] == "[视频内容] 视频摘要"


# ── fetch 边界 ──


async def test_fetch_article_content_empty_url_returns_empty():
    assert await content.fetch_article_content("") == ""


async def test_fetch_article_content_via_jina_empty_url_returns_empty():
    assert await content.fetch_article_content_via_jina("") == ""
