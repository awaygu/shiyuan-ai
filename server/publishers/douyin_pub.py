"""抖音发布 — Playwright browser automation."""

from __future__ import annotations

import asyncio
import logging

from .base import BrowserPublisher, PublishResult, NeedLoginError, random_delay
from config import PUBLISH_MANUAL_TIMEOUT

logger = logging.getLogger(__name__)


class DouyinPublisher(BrowserPublisher):
    login_url = "https://creator.douyin.com"
    login_check_url = "https://creator.douyin.com/creator-micro/home"
    publish_url = "https://creator.douyin.com/creator-micro/content/upload"

    def __init__(self):
        super().__init__("douyin")

    async def _detect_login(self, page) -> bool:
        current_url = page.url
        if "login" in current_url.lower():
            return False
        try:
            avatar = await page.query_selector(
                "[class*='avatar'], [class*='user-info'], [class*='header-user']"
            )
            if avatar:
                return True
        except Exception:
            pass
        if "creator.douyin.com" in current_url and "login" not in current_url.lower():
            return True
        return False

    async def _do_publish(self, page, title: str, content: str) -> PublishResult:
        await page.goto(self.publish_url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        await random_delay(2, 4)

        if "login" in page.url.lower():
            raise NeedLoginError("抖音登录已过期，请重新扫码登录")

        title_input = await page.query_selector(
            "input[placeholder*='标题'], input[placeholder*='填写'], .editor-title input"
        )
        if title_input:
            await title_input.click()
            await random_delay(0.5, 1)
            await title_input.fill(title[:30])
            await random_delay(1, 2)
        else:
            logger.warning("Title input not found for douyin")

        editor = await page.query_selector(
            "[contenteditable='true'], .ql-editor, .editor-content, textarea"
        )
        if editor:
            await editor.click()
            await random_delay(0.5, 1)
            plain_text = content.replace("**", "").replace("*", "").replace("#", "").replace(">", "")
            tag = " " + " ".join(f"#{w.strip()}" for w in title.split() if w.strip())[:100]
            full_text = plain_text + "\n" + tag
            paragraphs = [p.strip() for p in full_text.split("\n") if p.strip()]
            for para in paragraphs[:50]:
                await page.keyboard.type(para)
                await page.keyboard.press("Enter")
                await random_delay(0.3, 0.8)
        else:
            logger.warning("Content editor not found for douyin")

        await random_delay(3, 5)

        await self._progress("内容已填好，请在浏览器窗口检查后手动点「发布」")

        published = False
        for _ in range(PUBLISH_MANUAL_TIMEOUT):
            await asyncio.sleep(1)
            current_url = page.url
            if "/content/upload" not in current_url and "upload" not in current_url:
                published = True
                break
            try:
                toast = await page.query_selector(
                    "text=发布成功 >> visible=true, [class*='success']:has-text('发布'), .toast:has-text('成功')"
                )
                if toast:
                    published = True
                    break
            except Exception:
                pass

        if published:
            return PublishResult(
                success=True,
                platform=self.platform_name,
                article_title=title,
                published_url="https://creator.douyin.com/creator-micro/content/manage",
            )
        return PublishResult(
            success=True,
            platform=self.platform_name,
            article_title=title,
            published_url="",
            error_message="内容已填好但未发布：请在浏览器窗口手动点「发布」",
        )
