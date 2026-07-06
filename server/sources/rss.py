"""RSS crawler for fetching news from RSS/Atom/JSON feeds.

Supports:
- RSS 2.0
- Atom
- JSON Feed 1.1

Reference: TrendRadar RSS implementation
"""

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .base import BaseCrawler, NewsItem

try:
    import feedparser

    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    feedparser = None


@dataclass
class RSSFeedConfig:
    """RSS feed configuration."""

    id: str
    name: str
    url: str
    max_items: int = 0
    enabled: bool = True


DEFAULT_RSS_FEEDS = [
    RSSFeedConfig("hacker-news", "Hacker News", "https://hnrss.org/frontpage"),
    RSSFeedConfig("ruanyifeng", "阮一峰的网络日志", "http://www.ruanyifeng.com/blog/atom.xml"),
]


@dataclass
class ParsedRSSItem:
    """Parsed RSS item."""

    title: str
    url: str
    published_at: str | None = None
    summary: str | None = None
    author: str | None = None


class RSSParser:
    """RSS/Atom/JSON Feed parser."""

    def __init__(self, max_summary_length: int = 500):
        if not HAS_FEEDPARSER:
            raise ImportError("RSS parsing requires feedparser. Install with: pip install feedparser")
        self.max_summary_length = max_summary_length

    def parse(self, content: str, feed_url: str = "") -> list[ParsedRSSItem]:
        """Parse RSS/Atom/JSON Feed content."""
        if self._is_json_feed(content):
            return self._parse_json_feed(content, feed_url)

        feed = feedparser.parse(content)

        if feed.bozo and not feed.entries:
            raise ValueError(f"RSS parse error ({feed_url}): {feed.bozo_exception}")

        items = []
        for entry in feed.entries:
            item = self._parse_entry(entry)
            if item:
                items.append(item)

        return items

    def _is_json_feed(self, content: str) -> bool:
        """Check if content is JSON Feed format."""
        content = content.strip()
        if not content.startswith("{"):
            return False
        try:
            data = json.loads(content)
            version = data.get("version", "")
            return "jsonfeed.org" in version
        except (json.JSONDecodeError, TypeError):
            return False

    def _parse_json_feed(self, content: str, feed_url: str = "") -> list[ParsedRSSItem]:
        """Parse JSON Feed 1.1 format."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON Feed parse error ({feed_url}): {e}")

        items_data = data.get("items", [])
        if not items_data:
            return []

        items = []
        for item_data in items_data:
            item = self._parse_json_feed_item(item_data)
            if item:
                items.append(item)

        return items

    def _parse_json_feed_item(self, item_data: dict[str, Any]) -> ParsedRSSItem | None:
        """Parse single JSON Feed item."""
        title = item_data.get("title", "")
        if not title:
            content_text = item_data.get("content_text", "")
            if content_text:
                title = content_text[:100] + ("..." if len(content_text) > 100 else "")

        title = self._clean_text(title)
        if not title:
            return None

        url = item_data.get("url", "") or item_data.get("external_url", "")

        published_at = None
        date_str = item_data.get("date_published") or item_data.get("date_modified")
        if date_str:
            published_at = self._parse_iso_date(date_str)

        summary = item_data.get("summary", "")
        if not summary:
            content_text = item_data.get("content_text", "")
            content_html = item_data.get("content_html", "")
            summary = content_text or self._clean_text(content_html)

        if summary:
            summary = self._clean_text(summary)
            if len(summary) > self.max_summary_length:
                summary = summary[: self.max_summary_length] + "..."

        author = None
        authors = item_data.get("authors", [])
        if authors:
            names = [a.get("name", "") for a in authors if isinstance(a, dict) and a.get("name")]
            if names:
                author = ", ".join(names)

        return ParsedRSSItem(
            title=title,
            url=url,
            published_at=published_at,
            summary=summary or None,
            author=author,
        )

    def _parse_iso_date(self, date_str: str) -> str | None:
        """Parse ISO 8601 date format."""
        if not date_str:
            return None
        try:
            date_str = date_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(date_str)
            return dt.isoformat()
        except (ValueError, TypeError):
            pass
        return None

    def _parse_entry(self, entry: Any) -> ParsedRSSItem | None:
        """Parse single feed entry."""
        title = self._clean_text(entry.get("title", ""))
        if not title:
            return None

        url = entry.get("link", "")
        if not url:
            links = entry.get("links", [])
            for link in links:
                if link.get("rel") == "alternate" or link.get("type", "").startswith("text/html"):
                    url = link.get("href", "")
                    break
            if not url and links:
                url = links[0].get("href", "")

        published_at = self._parse_date(entry)
        summary = self._parse_summary(entry)
        author = self._parse_author(entry)

        return ParsedRSSItem(
            title=title,
            url=url,
            published_at=published_at,
            summary=summary,
            author=author,
        )

    def _clean_text(self, text: str) -> str:
        """Clean text content."""
        if not text:
            return ""
        text = html.unescape(text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _parse_date(self, entry: Any) -> str | None:
        """Parse publication date."""
        date_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if date_struct:
            try:
                dt = datetime(*date_struct[:6])
                return dt.isoformat()
            except (ValueError, TypeError):
                pass

        date_str = entry.get("published") or entry.get("updated")
        if date_str:
            try:
                from email.utils import parsedate_to_datetime

                dt = parsedate_to_datetime(date_str)
                return dt.isoformat()
            except (ValueError, TypeError):
                pass
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return dt.isoformat()
            except (ValueError, TypeError):
                pass
        return None

    def _parse_summary(self, entry: Any) -> str | None:
        """Parse summary/description."""
        summary = entry.get("summary") or entry.get("description", "")
        if not summary:
            content = entry.get("content", [])
            if content and isinstance(content, list):
                summary = content[0].get("value", "")
        if not summary:
            return None
        summary = self._clean_text(summary)
        if len(summary) > self.max_summary_length:
            summary = summary[: self.max_summary_length] + "..."
        return summary

    def _parse_author(self, entry: Any) -> str | None:
        """Parse author."""
        author = entry.get("author")
        if author:
            return self._clean_text(author)
        author = entry.get("dc_creator")
        if author:
            return self._clean_text(author)
        authors = entry.get("authors", [])
        if authors:
            names = [a.get("name", "") for a in authors if a.get("name")]
            if names:
                return ", ".join(names)
        return None


class RSSCrawler(BaseCrawler):
    """RSS feed crawler."""

    def __init__(self, feed: RSSFeedConfig):
        super().__init__(feed.id)
        self.feed = feed
        self.parser = RSSParser()

    async def crawl(self) -> list[NewsItem]:
        """Crawl news from RSS feed."""
        try:
            content = await self._fetch(
                self.feed.url,
                headers={
                    "User-Agent": "NewsInterpretation/1.0 RSS Reader",
                    "Accept": (
                        "application/feed+json, application/json, "
                        "application/rss+xml, application/atom+xml, "
                        "application/xml, text/xml, */*"
                    ),
                },
            )

            parsed_items = self.parser.parse(content, self.feed.url)

            if self.feed.max_items > 0:
                parsed_items = parsed_items[: self.feed.max_items]

            items = []
            seen = set()

            for parsed in parsed_items:
                dedup_key = hashlib.md5(parsed.title.encode()).hexdigest()[:12]
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                pub_time = datetime.now()
                if parsed.published_at:
                    try:
                        pub_time = datetime.fromisoformat(parsed.published_at.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass

                items.append(
                    NewsItem(
                        news_id=f"rss_{self.feed.id}_{dedup_key}",
                        title=parsed.title,
                        summary=parsed.summary or parsed.title[:200],
                        source=self.feed.id,
                        url=parsed.url,
                        published_at=pub_time,
                        extra={
                            "author": parsed.author,
                            "feed_name": self.feed.name,
                        },
                    )
                )

            return items

        except Exception as e:
            print(f"[RSS] {self.feed.name}: Error - {e}")
            return []


class RSSBatchCrawler:
    """Batch crawler for multiple RSS feeds."""

    def __init__(self, feeds: list[RSSFeedConfig] | None = None):
        self.feeds = [f for f in (feeds or DEFAULT_RSS_FEEDS) if f.enabled]
        self._crawlers = [RSSCrawler(feed) for feed in self.feeds]

    async def crawl_all(self) -> dict[str, list[NewsItem]]:
        """Crawl all RSS feeds."""
        results: dict[str, list[NewsItem]] = {}

        for crawler in self._crawlers:
            try:
                items = await crawler.crawl()
                results[crawler.feed.id] = items
                print(f"[RSS] {crawler.feed.name}: {len(items)} items")
            except Exception as e:
                print(f"[RSS] {crawler.feed.name}: Error - {e}")
                results[crawler.feed.id] = []

        return results

    def get_feed_names(self) -> dict[str, str]:
        """Get mapping of feed ID to display name."""
        return {feed.id: feed.name for feed in self.feeds}
