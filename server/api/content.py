"""Article content fetching, cleaning, and on-demand ensure logic.

The largest cluster in the original ``deps.py`` (~245 lines): fetching
article HTML, cleaning Jina Reader output, extracting meta descriptions,
handling JS-rendered and video sources, and the ``ensure_content``
entrypoint that lazily fills in ``item["content"]``.

Depends only on ``httpx``, ``config.JS_RENDERED_SOURCES`` /
``config.JINA_READER_URL``, and ``database.update_news_content`` — no
deps on other ``api`` modules, so there is no cycle with stores /
singletons / crawlers.
"""

from __future__ import annotations

import logging

import httpx

from config import JINA_READER_URL
from database import update_news_content

logger = logging.getLogger(__name__)

# JS 渲染型源：直接 httpx 抓不到正文，必须走 Jina Reader；
# 列表与 sources/newsnow.py 的平台 alias 对齐。
JS_RENDERED_SOURCES = {"toutiao", "cankaoxiaoxi", "weibo", "wallstreetcn-hot", "thepaper"}


async def fetch_article_content(url: str) -> str:
    """Fetch and extract main text content from a URL."""
    if not url:
        return ""
    try:
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            resp.raise_for_status()
            resp.encoding = resp.charset_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")

            for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
                tag.decompose()

            candidates = [
                soup.find("article"),
                soup.find(
                    "div",
                    class_=lambda c: (
                        c
                        and any(k in str(c).lower() for k in ["article", "content", "post", "entry", "detail", "body"])
                    ),
                ),
                soup.find(
                    "div",
                    id=lambda i: (
                        i
                        and any(k in str(i).lower() for k in ["article", "content", "post", "entry", "detail", "body"])
                    ),
                ),
            ]
            main = next((c for c in candidates if c), soup.find("body") or soup)
            paragraphs = main.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"])
            if paragraphs:
                parts = []
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    if len(text) > 10:
                        tag = p.name
                        if tag.startswith("h"):
                            parts.append(f"{'#' * int(tag[1])} {text}")
                        elif tag == "blockquote":
                            parts.append(f"> {text}")
                        else:
                            parts.append(text)
                result = "\n\n".join(parts)[:10000]
                if len(result) > 100:
                    return result

            body_text = main.get_text(separator="\n", strip=True)[:5000]
            if len(body_text) > 200:
                return body_text

            meta = _extract_meta_description(soup)
            if meta:
                return meta

            return body_text
    except Exception as e:
        logger.warning("Failed to fetch content from %s: %s", url, e)
        return ""


def _clean_jina_content(text: str) -> str:
    """Clean noise from Jina Reader output (headers, nav links, broken images, etc.)."""
    import re

    lines = text.split("\n")
    cleaned = []
    skip_patterns = [
        re.compile(r"^Title:\s*", re.IGNORECASE),
        re.compile(r"^URL Source:\s*", re.IGNORECASE),
        re.compile(r"^Markdown Content:\s*", re.IGNORECASE),
    ]
    for line in lines:
        stripped = line.strip()
        if any(p.match(stripped) for p in skip_patterns):
            continue
        if re.match(r"^`https?://\S+`\s*$", stripped):
            continue
        if re.match(r"^`https?://\S+`\s*\]\(https?://\S+\)\s*$", stripped):
            continue
        if re.match(r"^!\s*`https?://\S+`\s*$", stripped):
            continue
        if re.match(r"^!\s*`https?://\S+`\s+\]\(https?://\S+\)\s*$", stripped):
            continue
        if re.match(r"^\[`\s*$", stripped):
            continue
        cleaned.append(line)

    text = "\n".join(cleaned)

    text = re.sub(r"!\s*`https?://\S+?`(\s*\]\(https?://\S+?\))?", "", text)
    text = re.sub(r"\[`https?://\S+?`\]\(https?://\S+?\)", "", text)
    text = re.sub(r"`https?://\S+?`(\s*\]\(https?://\S+?\))?", "", text)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def fetch_article_content_via_jina(url: str) -> str:
    """Fetch article content via Jina Reader (handles JS-rendered pages)."""
    if not url:
        return ""
    jina_url = f"{JINA_READER_URL}/{url}"
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(
                jina_url,
                headers={
                    "Accept": "text/plain",
                },
            )
            resp.raise_for_status()
            text = resp.text.strip()
            if len(text) > 100:
                text = _clean_jina_content(text)
                if len(text) > 100:
                    return text[:10000]
            return ""
    except Exception as e:
        logger.warning("Jina Reader failed for %s: %s", url, e)
        return ""


def _extract_meta_description(soup) -> str:
    """Extract article description from meta tags as fallback."""
    parts = []

    og_desc = soup.find("meta", attrs={"property": "og:description"})
    if og_desc and og_desc.get("content"):
        text = og_desc["content"].strip()
        if len(text) > 30:
            parts.append(text)

    if not parts:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            text = meta_desc["content"].strip()
            if len(text) > 30:
                parts.append(text)

    for ld in soup.find_all("script", type="application/ld+json"):
        try:
            import json

            data = json.loads(ld.string or "")
            if isinstance(data, dict):
                for key in ("articleBody", "description", "text"):
                    val = data.get(key, "")
                    if val and len(str(val)) > 30:
                        parts.append(str(val).strip())
                        break
                if not parts:
                    for key in ("articleBody", "description"):
                        val = data.get("@graph", [{}])[0].get(key, "") if data.get("@graph") else ""
                        if val and len(str(val)) > 30:
                            parts.append(str(val).strip())
                            break
        except Exception as e:
            # ld+json 结构各异，解析失败逐条跳过属正常；记 debug 避免噪音，
            # 保留可排查性（正文分节提取为尽力而为，不影响主流程）。
            logger.debug("Failed to parse ld+json block: %s", e)
            continue

    return "\n\n".join(parts)[:5000] if parts else ""


async def ensure_content(item: dict) -> None:
    """Ensure a news item has real article content, fetching on-demand if needed."""
    existing = item.get("content", "")
    summary = item.get("summary", "")
    if existing and existing != summary and not existing.startswith(summary[:50]):
        return

    media_type = (
        item.get("extra", {}).get("media_type", "article") if isinstance(item.get("extra"), dict) else "article"
    )

    if media_type == "video":
        await _ensure_video_content(item)
        return

    source = item.get("source", "")
    url = item.get("url", "")
    if not url:
        return

    if source in JS_RENDERED_SOURCES:
        content = await fetch_article_content_via_jina(url)
        if content:
            # 先落库（DB 事实来源），再原地更新缓存条目（item 是 find_news 返回的共享对象）。
            await update_news_content(item["news_id"], content)
            item["content"] = content
            return
        _ensure_limited_content(item)
        return

    content = await fetch_article_content(url)
    if content:
        await update_news_content(item["news_id"], content)
        item["content"] = content
    else:
        content = await fetch_article_content_via_jina(url)
        if content:
            await update_news_content(item["news_id"], content)
            item["content"] = content
        else:
            _ensure_limited_content(item)


def _ensure_limited_content(item: dict) -> None:
    """Set limited content for JS-rendered or failed-fetch sources."""
    summary = item.get("summary", "")
    title = item.get("title", "")
    parts = ["[全文需在浏览器中查看]"]
    if title:
        parts.append(f"标题：{title}")
    if summary and summary != title:
        parts.append(f"摘要：{summary}")
    item["content"] = "\n".join(parts)


def is_limited_content(item: dict) -> bool:
    """Check if the item has limited content (cannot be processed by AI)."""
    content = item.get("content", "")
    return content.startswith("[全文需在浏览器中查看]")


async def _ensure_video_content(item: dict) -> None:
    """Extract metadata from video pages (description, tags, etc.)."""
    summary = item.get("summary", "")
    url = item.get("url", "")
    if not url:
        return

    metadata = await _extract_video_metadata(url)
    if metadata:
        parts = []
        if metadata.get("description"):
            parts.append(f"视频简介：{metadata['description']}")
        if metadata.get("tags"):
            parts.append(f"标签：{', '.join(metadata['tags'])}")
        if metadata.get("author"):
            parts.append(f"作者：{metadata['author']}")
        if metadata.get("stats"):
            parts.append(metadata["stats"])
        if parts:
            content = "\n".join(parts)
            # 先落库（DB 事实来源），再原地更新缓存条目。
            await update_news_content(item["news_id"], content)
            item["content"] = content
            return

    if summary:
        item["content"] = f"[视频内容] {summary}"


async def _extract_video_metadata(url: str) -> dict | None:
    """Try to extract metadata from a video page."""
    try:
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            resp.raise_for_status()
            resp.encoding = resp.charset_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")

            result = {}

            desc_tag = soup.find("meta", attrs={"name": "description"})
            if desc_tag and desc_tag.get("content"):
                result["description"] = desc_tag["content"].strip()[:500]

            kw_tag = soup.find("meta", attrs={"name": "keywords"})
            if kw_tag and kw_tag.get("content"):
                tags = [t.strip() for t in kw_tag["content"].split(",") if t.strip()]
                if tags:
                    result["tags"] = tags[:10]

            og_title = soup.find("meta", attrs={"property": "og:title"})
            author_tag = soup.find("meta", attrs={"name": "author"})
            if not author_tag:
                author_tag = soup.find("meta", attrs={"property": "og:article:author"})
            if not author_tag and og_title and og_title.get("content"):
                author_tag = og_title
            if author_tag and author_tag.get("content"):
                result["author"] = author_tag["content"].strip()

            stats_parts = []
            for og_stat in [
                ("og:video:duration", "时长"),
                ("og:video:view_count", "播放量"),
            ]:
                stat_tag = soup.find("meta", attrs={"property": og_stat[0]})
                if stat_tag and stat_tag.get("content"):
                    stats_parts.append(f"{og_stat[1]}: {stat_tag['content']}")
            if stats_parts:
                result["stats"] = " | ".join(stats_parts)

            return result if result else None
    except Exception as e:
        logger.warning("Failed to extract video metadata from %s: %s", url, e)
        return None
