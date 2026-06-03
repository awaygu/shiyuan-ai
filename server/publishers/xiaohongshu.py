"""小红书发布 — Playwright browser automation."""

from __future__ import annotations

import logging

from .base import BrowserPublisher, PublishResult, NeedLoginError, random_delay

logger = logging.getLogger(__name__)


class XiaohongshuPublisher(BrowserPublisher):
    login_url = "https://creator.xiaohongshu.com"
    login_check_url = "https://creator.xiaohongshu.com/creator/home"
    publish_url = "https://creator.xiaohongshu.com/publish/publish"

    def __init__(self):
        super().__init__("xiaohongshu")

    async def _detect_login(self, page) -> bool:
        current_url = page.url
        logger.debug("XHS _detect_login: url=%s", current_url)
        if "login" in current_url.lower():
            return False
        try:
            avatar = await page.query_selector(".user-avatar, .avatar, .creator-avatar, [class*='avatar']")
            logger.debug("XHS _detect_login: avatar=%s", avatar is not None)
            if avatar:
                return True
        except Exception:
            pass
        if "creator.xiaohongshu.com" in current_url and "login" not in current_url.lower():
            logger.debug("XHS _detect_login: on creator page, assuming logged in")
            return True
        return False

    async def _do_publish(self, page, title: str, content: str) -> PublishResult:
        await page.goto(self.publish_url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        await random_delay(2, 4)

        if "login" in page.url.lower():
            raise NeedLoginError("小红书登录已过期，请重新扫码登录")

        title_input = await page.query_selector(
            "input[placeholder='填写标题'], input[placeholder*='标题'], .c-input_inner"
        )
        if not title_input:
            title_input = await page.query_selector("input[maxlength='20']")
        if title_input:
            await title_input.click()
            await random_delay(0.5, 1)
            await title_input.fill(title[:20])
            await random_delay(1, 2)
        else:
            logger.warning("Title input not found for xiaohongshu")

        editor = await page.query_selector(".ql-editor, [contenteditable='true'], .ce-editor")
        if editor:
            await editor.click()
            await random_delay(0.5, 1)
            plain_text = content.replace("**", "").replace("*", "").replace("#", "").replace(">", "")
            paragraphs = [p.strip() for p in plain_text.split("\n") if p.strip()]
            for para in paragraphs[:50]:
                await page.keyboard.type(para)
                await page.keyboard.press("Enter")
                await random_delay(0.3, 0.8)
        else:
            logger.warning("Content editor not found for xiaohongshu")

        await random_delay(3, 5)

        publish_btn = await page.query_selector(
            "button:has-text('发布'), button:has-text('发表'), [class*='publish']"
        )
        if publish_btn:
            await publish_btn.click()
            await random_delay(2, 4)
            await page.wait_for_load_state("networkidle", timeout=30000)
        else:
            logger.warning("Publish button not found for xiaohongshu")

        current_url = page.url
        success = "publish" not in current_url or "success" in current_url.lower()

        return PublishResult(
            success=success,
            platform=self.platform_name,
            article_title=title,
            published_url=f"https://www.xiaohongshu.com/user/profile/self" if success else "",
            error_message="" if success else "发布可能未成功，请检查小红书创作者后台",
        )
