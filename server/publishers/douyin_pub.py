"""抖音发布 — Playwright browser automation."""

from __future__ import annotations

import logging

from .base import BrowserPublisher, PublishResult, NeedLoginError, random_delay

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

        publish_btn = await page.query_selector(
            "button:has-text('发布'), button:has-text('发表'), [class*='publish-btn']"
        )
        if publish_btn:
            await publish_btn.click()
            await random_delay(2, 4)
            await page.wait_for_load_state("networkidle", timeout=30000)
        else:
            logger.warning("Publish button not found for douyin")

        current_url = page.url
        success = "upload" not in current_url or "success" in current_url.lower()

        return PublishResult(
            success=success,
            platform=self.platform_name,
            article_title=title,
            published_url=f"https://www.douyin.com/user/self" if success else "",
            error_message="" if success else "发布可能未成功，请检查抖音创作者中心",
        )
