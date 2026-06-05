"""Base publisher class."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config import COOKIES_DIR, PUBLISH_HEADLESS, PUBLISH_TIMEOUT

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """Result of a publish attempt."""
    success: bool
    platform: str
    article_title: str
    published_url: str = ""
    error_message: str = ""
    need_login: bool = False
    published_at: datetime = field(default_factory=datetime.now)
    extra: dict[str, Any] = field(default_factory=dict)


class NeedLoginError(Exception):
    """Raised when platform requires user to re-login."""
    def __init__(self, message: str = "Login required"):
        super().__init__(message)
        self.message = message


class BasePublisher(ABC):
    """Abstract base class for all platform publishers."""

    def __init__(self, platform_name: str):
        self.platform_name = platform_name

    @abstractmethod
    async def publish(
        self,
        title: str,
        content: str,
        **kwargs: Any,
    ) -> PublishResult:
        """Publish article to the platform."""
        ...

    @abstractmethod
    async def check_login(self) -> bool:
        """Check if login state is valid."""
        ...

    @abstractmethod
    async def do_login(self) -> bool:
        """Trigger login flow. Returns True on success."""
        ...


async def random_delay(min_s: float = 1.0, max_s: float = 3.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


def _run_playwright(coro):
    """Run an async playwright coroutine in a ProactorEventLoop thread.

    On Windows, SelectorEventLoop does not support subprocesses,
    which Playwright needs to launch its browser process.
    """
    if sys.platform != "win32":
        return asyncio.run(coro)
    loop = asyncio.ProactorEventLoop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class BrowserPublisher(BasePublisher):
    """Playwright browser automation publisher base class."""

    login_url: str = ""
    publish_url: str = ""
    login_check_url: str = ""

    def __init__(self, platform_name: str):
        super().__init__(platform_name)
        self.cookies_path = Path(COOKIES_DIR) / f"{platform_name}.json"
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._last_login_error: str = ""

    def load_cookies(self) -> dict | None:
        if not self.cookies_path.exists():
            return None
        try:
            return json.loads(self.cookies_path.read_text("utf-8"))
        except Exception:
            logger.warning("Failed to load cookies from %s", self.cookies_path)
            return None

    def save_cookies(self, storage_state: dict) -> None:
        self.cookies_path.write_text(
            json.dumps(storage_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved cookies to %s", self.cookies_path)

    async def check_login(self) -> bool:
        cookies = self.load_cookies()
        if not cookies:
            return False
        if not cookies.get("cookies"):
            return False
        try:
            return await asyncio.to_thread(_run_playwright, self._check_login_impl(cookies))
        except Exception as e:
            logger.warning("Login check failed for %s: %s", self.platform_name, e)
            return False

    async def _check_login_impl(self, cookies):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=cookies)
            page = await context.new_page()
            await page.goto(self.login_check_url or self.login_url, timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=10000)
            logged_in = await self._detect_login(page)
            await browser.close()
            return logged_in

    async def _detect_login(self, page) -> bool:
        raise NotImplementedError

    async def do_login(self) -> bool:
        self._last_login_error = ""
        try:
            result = await asyncio.to_thread(_run_playwright, self._do_login_impl())
            if not result and not self._last_login_error:
                self._last_login_error = f"登录超时（{PUBLISH_TIMEOUT}秒内未完成扫码），请重试"
                logger.warning("Login timeout for %s after %ds", self.platform_name, PUBLISH_TIMEOUT)
            return result
        except Exception as e:
            self._last_login_error = f"浏览器启动失败: {e}"
            logger.error("Login failed for %s: %s", self.platform_name, e, exc_info=True)
            return False

    async def _do_login_impl(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()
            logger.info("Navigating to %s ...", self.login_url)
            await page.goto(self.login_url, timeout=30000)
            logger.info("Page loaded: %s, title: %s", page.url, await page.title())

            for i in range(PUBLISH_TIMEOUT):
                await asyncio.sleep(1)
                current_url = page.url
                logged_in = await self._detect_login(page)
                logger.debug("Login poll %d/%d: url=%s, logged_in=%s", i + 1, PUBLISH_TIMEOUT, current_url, logged_in)
                if logged_in:
                    storage_state = await context.storage_state()
                    self.save_cookies(storage_state)
                    logger.info("Login successful for %s", self.platform_name)
                    await browser.close()
                    return True

            logger.warning("Login timeout for %s after %ds", self.platform_name, PUBLISH_TIMEOUT)
            await browser.close()
            return False

    async def publish(self, title: str, content: str, **kwargs) -> PublishResult:
        async with self._lock:
            cookies = self.load_cookies()
            if not cookies:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    article_title=title,
                    need_login=True,
                    error_message="Not logged in, please scan QR code first",
                )

            try:
                return await asyncio.to_thread(
                    _run_playwright,
                    self._publish_impl(cookies, title, content),
                )
            except Exception as e:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    article_title=title,
                    error_message=f"Browser error: {e}",
                )

    async def _publish_impl(self, cookies, title, content):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            headless = PUBLISH_HEADLESS
            browser = await pw.chromium.launch(headless=headless)
            context = await browser.new_context(storage_state=cookies)
            page = await context.new_page()

            try:
                result = await self._do_publish(page, title, content)

                storage_state = await context.storage_state()
                self.save_cookies(storage_state)

                return result
            except NeedLoginError as e:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    article_title=title,
                    need_login=True,
                    error_message=str(e),
                )
            except Exception as e:
                logger.error("Publish failed for %s: %s", self.platform_name, e)
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    article_title=title,
                    error_message=str(e),
                )
            finally:
                await browser.close()

    async def _do_publish(self, page, title: str, content: str) -> PublishResult:
        raise NotImplementedError
