"""NewsNow API unified crawler.

Supports two deployment modes:
- Local Docker (recommended): http://localhost:4444/api/s
- Public instance (fallback): https://newsnow.busiyi.world/api/s

The crawler reads NEWSNOW_API_URL from config.py (which loads from .env).
If the primary API is unreachable, it automatically falls back to the
public instance.

Supported platforms:
- cls-hot: 财联社热门
- cls-telegraph: 财联社电报
- wallstreetcn-hot: 华尔街见闻
- cankaoxiaoxi: 参考消息
- thepaper: 澎湃新闻
- toutiao: 今日头条
- xueqiu: 雪球
- weibo: 微博
- douyin: 抖音
"""

import asyncio
import hashlib
import json
import logging
import random
from datetime import datetime
from typing import Any

import requests as req_lib

from .base import BaseCrawler, NewsItem

logger = logging.getLogger(__name__)

PLATFORM_CONFIG = {
    "cls-hot": {"name": "财联社热门", "alias": "cls_hot"},
    "cls-telegraph": {"name": "财联社电报", "alias": "cls_telegraph"},
    "wallstreetcn-hot": {"name": "华尔街见闻", "alias": "wallstreet"},
    "cankaoxiaoxi": {"name": "参考消息", "alias": "cankao"},
    "thepaper": {"name": "澎湃新闻", "alias": "pengpai"},
    "toutiao": {"name": "今日头条", "alias": "toutiao"},
    "xueqiu": {"name": "雪球", "alias": "xueqiu"},
    "weibo": {"name": "微博", "alias": "weibo"},
    "douyin": {"name": "抖音", "alias": "douyin", "media_type": "video"},
}

VIDEO_PLATFORMS = {"douyin"}

FALLBACK_API_URL = "https://newsnow.busiyi.world/api/s"


async def check_newsnow_health(base_url: str, timeout: float = 3.0) -> bool:
    try:
        api_url = f"{base_url}?id=weibo"
        resp = await asyncio.to_thread(
            req_lib.get, api_url, timeout=timeout,
        )
        data = resp.json()
        return data.get("status") in ("success", "cache")
    except Exception:
        return False


class NewsNowCrawler(BaseCrawler):
    """Unified crawler using NewsNow API."""

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.124 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }

    def __init__(
        self,
        platform_id: str,
        api_url: str | None = None,
        max_retries: int = 1,
        retry_wait_min: int = 1,
        retry_wait_max: int = 2,
    ):
        if platform_id not in PLATFORM_CONFIG:
            raise ValueError(
                f"Unknown platform: {platform_id}. "
                f"Available: {list(PLATFORM_CONFIG.keys())}"
            )
        super().__init__(PLATFORM_CONFIG[platform_id]["alias"])
        self.platform_id = platform_id
        self.platform_name = PLATFORM_CONFIG[platform_id]["name"]
        self.alias = PLATFORM_CONFIG[platform_id]["alias"]
        self.api_url = api_url
        self.max_retries = max_retries
        self.retry_wait_min = retry_wait_min
        self.retry_wait_max = retry_wait_max

    def _resolve_api_url(self) -> str:
        if self.api_url:
            return self.api_url
        try:
            from config import NEWSNOW_API_URL
            return NEWSNOW_API_URL
        except ImportError:
            return FALLBACK_API_URL

    async def crawl(self) -> list[NewsItem]:
        base = self._resolve_api_url()
        url = f"{base}?id={self.platform_id}"
        data = await self._fetch_with_retry(url)
        if not data:
            if base != FALLBACK_API_URL:
                logger.warning(
                    "[%s] Primary API failed, trying fallback: %s",
                    self.platform_name, FALLBACK_API_URL,
                )
                fallback_url = f"{FALLBACK_API_URL}?id={self.platform_id}"
                data = await self._fetch_with_retry(fallback_url)
            if not data:
                return self._mock_fallback()

        items = []
        seen = set()

        raw_items = data.get("items", [])
        for rank, entry in enumerate(raw_items, 1):
            title = entry.get("title")
            if title is None or isinstance(title, float) or not str(title).strip():
                continue
            title = str(title).strip()

            dedup_key = hashlib.md5(title.encode()).hexdigest()[:12]
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            item_url = entry.get("url", "")
            mobile_url = entry.get("mobileUrl", "")

            if self.platform_id == "toutiao" and item_url:
                import re
                tid_match = re.search(r"/(\d+)/?", item_url)
                if tid_match:
                    item_url = f"https://www.toutiao.com/article/{tid_match.group(1)}/"

            if self.platform_id == "toutiao" and mobile_url:
                import re
                tid_match = re.search(r"/(\d+)/?", mobile_url)
                if tid_match:
                    mobile_url = f"https://www.toutiao.com/article/{tid_match.group(1)}/"

            pub_ts = entry.get("pubDate")
            if pub_ts and isinstance(pub_ts, (int, float)):
                published_at = datetime.fromtimestamp(pub_ts / 1000)
            else:
                published_at = datetime.now()

            items.append(NewsItem(
                news_id=f"{self.alias}_{dedup_key}",
                title=title,
                summary=title[:200],
                source=self.platform_id,
                url=mobile_url or item_url,
                published_at=published_at,
                media_type=PLATFORM_CONFIG[self.platform_id].get("media_type", "article"),
                extra={"original_url": item_url},
            ))

        return items if items else self._mock_fallback()

    async def _fetch_with_retry(self, url: str) -> dict | None:
        retries = 0
        while retries <= self.max_retries:
            try:
                text = await self._fetch(url, headers=self.DEFAULT_HEADERS)
                data = json.loads(text)

                status = data.get("status", "")
                if status not in ["success", "cache"]:
                    raise ValueError(f"API status error: {status}")

                return data

            except Exception as e:
                retries += 1
                if retries <= self.max_retries:
                    wait = random.uniform(self.retry_wait_min, self.retry_wait_max)
                    wait += (retries - 1) * random.uniform(1, 2)
                    await asyncio.sleep(wait)
                else:
                    logger.warning("[%s] Fetch failed after %d retries: %s",
                                   self.platform_name, self.max_retries, e)
                    return None

        return None

    def _mock_fallback(self) -> list[NewsItem]:
        mocks = [
            (f"{self.platform_name}热点新闻1", "这是第一条热点新闻的详细描述"),
            (f"{self.platform_name}热点新闻2", "这是第二条热点新闻的详细描述"),
            (f"{self.platform_name}热点新闻3", "这是第三条热点新闻的详细描述"),
        ]
        return [
            NewsItem(
                f"{self.alias}_fb{i}",
                t,
                s,
                self.platform_id,
                published_at=datetime.now(),
            )
            for i, (t, s) in enumerate(mocks)
        ]


class NewsNowBatchCrawler:
    """Batch crawler for multiple platforms with concurrent requests."""

    def __init__(
        self,
        platform_ids: list[str] | None = None,
    ):
        self.platform_ids = platform_ids or list(PLATFORM_CONFIG.keys())
        self._crawlers: dict[str, NewsNowCrawler] = {}

        for pid in self.platform_ids:
            try:
                self._crawlers[pid] = NewsNowCrawler(pid)
            except ValueError as e:
                logger.warning("Skipping unknown platform: %s", e)

    async def crawl_all(self) -> dict[str, list[NewsItem]]:
        tasks = {}
        for pid, crawler in self._crawlers.items():
            tasks[pid] = asyncio.create_task(crawler.crawl())

        results: dict[str, list[NewsItem]] = {}
        for pid, task in tasks.items():
            try:
                items = await task
                results[pid] = items
                logger.info("[%s] Got %d items", self._crawlers[pid].platform_name, len(items))
            except Exception as e:
                logger.warning("[%s] Error: %s", self._crawlers[pid].platform_name, e)
                results[pid] = []

        return results

    def get_platform_names(self) -> dict[str, str]:
        return {
            crawler.alias: crawler.platform_name
            for crawler in self._crawlers.values()
        }
