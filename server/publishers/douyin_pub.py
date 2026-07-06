"""抖音发布 — Playwright browser automation."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from pathlib import Path

from config import PUBLISH_MANUAL_TIMEOUT, UPLOAD_DIR

from .base import BrowserPublisher, NeedLoginError, PublishResult, random_delay
from .image_archive import archive_key, try_read_archive, write_archive

logger = logging.getLogger(__name__)

# 抖音图文最多 35 张，但建议控制在 9 张以内
DOUYIN_IMAGE_MAX = int(os.getenv("DOUYIN_IMAGE_MAX", "9"))
DOUYIN_IMAGE_CONCURRENCY = int(os.getenv("DOUYIN_IMAGE_CONCURRENCY", "1"))
DOUYIN_IMAGE_INTERVAL = float(os.getenv("DOUYIN_IMAGE_INTERVAL", "3"))

TMP_IMG_DIR = Path(UPLOAD_DIR) / "douyin_tmp"
TMP_IMG_DIR.mkdir(parents=True, exist_ok=True)

# 抖音图文发布页 URL（上传图片后自动跳转到此页）
POST_IMAGE_URL_PATTERN = "/content/post/image"
# 抖音内容管理页 URL（发布成功后跳转到此页）
MANAGE_URL_PATTERN = "/content/manage"


DEBUG_SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "debug_screenshots"


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
            avatar = await page.query_selector("[class*='avatar'], [class*='user-info'], [class*='header-user']")
            if avatar:
                return True
        except Exception:
            pass
        return "creator.douyin.com" in current_url and "login" not in current_url.lower()

    async def _shot(self, page, name: str) -> None:
        await asyncio.to_thread(DEBUG_SCREENSHOTS_DIR.mkdir, parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(DEBUG_SCREENSHOTS_DIR / name), full_page=True)
            logger.info("Douyin screenshot: %s", name)
        except Exception as e:
            logger.warning("Douyin screenshot failed: %s", e)

    async def _navigate_to_upload(self, page) -> bool:
        """导航到抖音发布页。如果当前不在 upload 页，先 goto，必要时重试。"""
        current = page.url
        logger.info("Douyin current url=%s", current)
        if "upload" in current.lower() or POST_IMAGE_URL_PATTERN in current.lower():
            return True

        # 如果在首页，尝试点击「发布作品」按钮
        if "creator.douyin.com" in current.lower() and "login" not in current.lower():
            try:
                btn = await page.query_selector("a[href*='upload'], button:has-text('发布'), [class*='publish']")
                if btn:
                    await btn.click()
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    await random_delay(2, 3)
                    if "upload" in page.url.lower():
                        logger.info("Douyin: navigated to upload via publish button")
                        return True
            except Exception as e:
                logger.debug("Douyin publish button click: %s", e)

        # 直接导航到发布页
        await page.goto(self.publish_url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        await random_delay(2, 4)

        if "upload" in page.url.lower():
            logger.info("Douyin: navigated to upload via goto")
            return True

        logger.warning("Douyin: not on upload page, url=%s", page.url)
        return False

    async def _switch_to_image_tab(self, page) -> bool:
        """在上传页切换到「图文」tab（抖音上传页默认是「视频」）。

        2024+ 抖音创作者中心的 tab 是 <div class="tab-item-xxx">发布图文</div>，
        不是 button 或 [role='tab']，需要用精确文本匹配。
        """
        # 方案1：用 Playwright get_by_text 精确匹配「发布图文」
        try:
            tab = page.get_by_text("发布图文", exact=True)
            await tab.wait_for(timeout=10000)
            await tab.click()
            await page.wait_for_load_state("networkidle", timeout=10000)
            await random_delay(2, 3)
            logger.info("Douyin: switched to image tab via get_by_text('发布图文')")
            return True
        except Exception as e:
            logger.debug("Douyin get_by_text failed: %s", e)

        # 方案2：CSS 选择器精确匹配 tab-item 中的「发布图文」
        css_sels = [
            "[class*='tab-item']:has-text('发布图文')",
            ".tab-item-BcCLTS:has-text('发布图文')",
            "[class*='tab']:has-text('发布图文')",
        ]
        for sel in css_sels:
            try:
                tab = page.locator(sel).first
                await tab.wait_for(timeout=5000)
                await tab.click()
                await page.wait_for_load_state("networkidle", timeout=10000)
                await random_delay(2, 3)
                logger.info("Douyin: switched to image tab via %s", sel)
                return True
            except Exception:
                continue

        # 方案3：JavaScript 直接查找并点击
        try:
            js_clicked = await page.evaluate("""
                () => {
                    const tabs = document.querySelectorAll('[class*="tab-item"]');
                    for (const tab of tabs) {
                        if (tab.textContent.trim() === '发布图文') {
                            tab.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            if js_clicked:
                await page.wait_for_load_state("networkidle", timeout=10000)
                await random_delay(2, 3)
                logger.info("Douyin: switched to image tab via JS click")
                return True
        except Exception as e:
            logger.debug("Douyin JS click failed: %s", e)

        logger.warning("Douyin: image tab not found, may already be on image mode")
        return False

    async def _generate_images(
        self,
        gen,
        title: str,
        content: str,
        generate_cover: bool,
        generate_inline: bool,
        tmp_dir: Path,
    ) -> list[Path]:
        """生成封面 + 正文图，带存档复用，返回路径列表。"""
        from core.image_generator import split_by_headings

        jobs: list[tuple[str, int, tuple, Path]] = []
        if generate_cover:
            jobs.append(("cover", 0, (title, content), archive_key("cover", title)))
        if generate_inline:
            try:
                sections = split_by_headings(content)
                max_inline = DOUYIN_IMAGE_MAX - 1 if generate_cover else DOUYIN_IMAGE_MAX
                for i, s in enumerate(sections[:max_inline], start=1):
                    key = archive_key("inline", s.title or "", s.text)
                    jobs.append(("inline", i, (s.title, s.text), key))
            except Exception as e:
                logger.warning("Douyin: split sections failed: %s", e)

        if not jobs:
            return []

        sem = asyncio.Semaphore(DOUYIN_IMAGE_CONCURRENCY)
        paths: list[Path] = []

        async def _gen_one(kind: str, idx: int, args: tuple, akey: Path) -> Path | None:
            out_name = "cover_0.jpg" if kind == "cover" else f"inline_{idx}.jpg"
            out_path = tmp_dir / out_name

            if try_read_archive(akey, out_path):
                return out_path

            try:
                data = await (gen.generate_cover_image(*args) if kind == "cover" else gen.generate_section_image(*args))
                out_path.write_bytes(data)
                write_archive(akey, data)
                return out_path
            except Exception as e:
                logger.warning("Douyin %s image failed: %s", kind, e)
                return None

        async def run_job(i: int, job: tuple) -> Path | None:
            async with sem:
                if i > 0:
                    await asyncio.sleep(DOUYIN_IMAGE_INTERVAL)
                return await _gen_one(*job)

        results = await asyncio.gather(
            *(run_job(i, j) for i, j in enumerate(jobs)),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Douyin image task error: %s", r)
            elif r is not None:
                paths.append(r)
        return paths

    async def _upload_images(self, page, image_paths: list[Path]) -> bool:
        """上传图片到抖音发布页，上传成功后页面会自动跳转到图文编辑页。

        优先直接 file input，降级 filechooser。
        """
        if not image_paths:
            return False
        str_paths = [str(p) for p in image_paths]

        # 方案1：直接找图文上传区带 accept 属性的 file input
        try:
            file_input = page.locator("input[type='file'][accept*='image']").first
            await file_input.wait_for(state="attached", timeout=10000)
            await file_input.set_input_files(str_paths)
            logger.info("Douyin: uploaded %d images", len(str_paths))
            # 等待页面跳转到图文编辑页（post/image）
            uploaded = await self._wait_for_post_page(page)
            return uploaded
        except Exception as e:
            logger.warning("Douyin file input upload: %s", e)

        # 方案2：兜底 — 点击上传按钮触发文件选择器
        try:
            trigger = page.locator(
                "button:has-text('上传'), [class*='upload-image'], [class*='add-image'], [class*='container-drag']"
            ).first
            await trigger.wait_for(timeout=8000)
            async with page.expect_file_chooser(timeout=15000) as fc_info:
                await trigger.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(str_paths)
            logger.info("Douyin: uploaded %d images via filechooser", len(str_paths))
            uploaded = await self._wait_for_post_page(page)
            return uploaded
        except Exception as e:
            logger.warning("Douyin filechooser upload: %s", e)
            return False

    async def _wait_for_post_page(self, page, timeout: int = 30) -> bool:
        """等待上传完成后页面跳转到图文编辑页（post/image）。

        上传图片后抖音会自动跳转到 /content/post/image 页面，
        该页面有标题输入框和正文编辑器。
        """
        logger.info("Douyin: waiting for post/image page redirect...")
        try:
            # 等待 URL 变化到 post/image 页面
            for _ in range(timeout):
                await asyncio.sleep(1)
                current_url = page.url
                if POST_IMAGE_URL_PATTERN in current_url.lower():
                    logger.info("Douyin: redirected to post/image page: %s", current_url)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await random_delay(2, 4)
                    # 等待标题输入框出现
                    try:
                        await page.wait_for_selector(
                            "input[placeholder*='标题'], input.semi-input",
                            timeout=15000,
                        )
                        logger.info("Douyin: title input appeared on post/image page")
                        return True
                    except Exception:
                        logger.warning("Douyin: title input not found on post/image page")
                        # 即使标题输入框没找到，页面已经跳转了
                        return True
            logger.warning("Douyin: did not redirect to post/image page within %ds", timeout)
            return False
        except Exception as e:
            logger.warning("Douyin: wait for post page failed: %s", e)
            return False

    async def _wait_for_title_input(self, page, timeout: int = 60) -> bool:
        """等待标题输入框出现（用于用户手动上传图片的场景）。"""
        try:
            await page.wait_for_selector(
                "input[placeholder*='标题'], input.semi-input, input[placeholder*='作品标题']",
                timeout=timeout * 1000,
            )
            return True
        except Exception:
            return False

    async def _fill_title(self, page, title: str) -> bool:
        """填写标题，返回是否成功。

        抖音图文编辑页的标题输入框：
        - <input type="text" class="semi-input semi-input-default" placeholder="添加作品标题">
        """
        sels = [
            "input[placeholder*='作品标题']",
            "input[placeholder*='标题']",
            "input.semi-input:not([type='checkbox']):not([type='radio'])",
            "input[placeholder*='填写']",
            ".editor-title input",
            "[class*='title'] input[type='text']",
        ]
        for sel in sels:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                el = await page.query_selector(sel)
                if el:
                    # 确保元素可见且可交互
                    is_visible = await el.is_visible()
                    if not is_visible:
                        continue
                    await el.click()
                    await random_delay(0.5, 1)
                    # 清空已有内容
                    await el.fill("")
                    await random_delay(0.3, 0.5)
                    # 抖音图文标题限制 20 字符
                    await el.fill(title[:20])
                    await random_delay(1, 2)
                    logger.info("Douyin: title filled via %s", sel)
                    return True
            except Exception:
                continue
        logger.warning("Douyin: title input not found")
        return False

    async def _fill_content(self, page, content: str, title: str) -> bool:
        """填写正文和话题标签，返回是否成功。

        抖音图文编辑页的正文编辑器：
        - <div class="zone-container editor-kit-container editor editor-comp-publish"
              data-slate-editor="true" contenteditable="true">
        """
        sels = [
            ".editor-comp-publish[data-slate-editor='true']",
            "[data-slate-editor='true']",
            ".editor-comp-publish",
            "[contenteditable='true'].editor-comp-publish",
            "[contenteditable='true']",
            ".ql-editor",
            ".editor-content",
            "textarea",
        ]
        editor = None
        for sel in sels:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                editor = await page.query_selector(sel)
                if editor:
                    is_visible = await editor.is_visible()
                    if not is_visible:
                        continue
                    break
            except Exception:
                continue
        if not editor:
            logger.warning("Douyin: content editor not found")
            return False

        await editor.click()
        await random_delay(0.5, 1)

        plain_text = content.replace("**", "").replace("*", "").replace("#", "").replace(">", "")
        tag = " " + " ".join(f"#{w.strip()}" for w in title.split() if w.strip())[:100]
        full_text = plain_text + "\n" + tag
        # 抖音图文正文上限 1000 字符
        full_text = full_text[:1000]
        paragraphs = [p.strip() for p in full_text.split("\n") if p.strip()]
        for para in paragraphs[:50]:
            await page.keyboard.type(para)
            await page.keyboard.press("Enter")
            await random_delay(0.3, 0.8)

        logger.info("Douyin: content filled, %d paragraphs", len(paragraphs[:50]))
        return True

    async def _do_publish(self, page, title: str, content: str, **kwargs) -> PublishResult:
        generate_cover = kwargs.get("generate_cover", True)
        generate_inline = kwargs.get("generate_inline_images", True)

        # 1. 确保在发布页
        on_upload = await self._navigate_to_upload(page)
        await self._shot(page, "douyin_01_upload_page.png")
        if not on_upload:
            await self._progress("未能进入抖音发布页，请手动进入并发布")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                article_title=title,
                error_message="未能进入抖音发布页",
            )

        if "login" in page.url.lower():
            raise NeedLoginError("抖音登录已过期，请重新扫码登录")

        # 2. 切换到「图文」tab（默认是「视频」）
        # 仅当还在 upload 页时才需要切换 tab；如果已经在 post/image 页则跳过
        if POST_IMAGE_URL_PATTERN not in page.url.lower():
            switched = await self._switch_to_image_tab(page)
            await self._shot(page, "douyin_02_image_tab.png")
            if not switched:
                await self._progress("未找到「发布图文」切换按钮，请手动切换到图文模式")
        else:
            switched = True
            logger.info("Douyin: already on post/image page, skip tab switch")

        # 3. 生成并上传图片
        image_paths: list[Path] = []
        tmp_dir: Path | None = None
        images_uploaded = False
        try:
            from config import DASHSCOPE_API_KEY, IMAGE_GEN_ENABLED, IMAGE_GEN_MODEL

            if IMAGE_GEN_ENABLED and DASHSCOPE_API_KEY:
                from core.image_generator import ImageGenerator

                gen = ImageGenerator(DASHSCOPE_API_KEY, IMAGE_GEN_MODEL)

                tmp_dir = TMP_IMG_DIR / uuid.uuid4().hex[:12]
                tmp_dir.mkdir(parents=True, exist_ok=True)
                image_paths = await self._generate_images(
                    gen,
                    title,
                    content,
                    generate_cover,
                    generate_inline,
                    tmp_dir,
                )
                if image_paths:
                    await self._progress(f"正在上传 {len(image_paths)} 张图片到抖音...")
                    images_uploaded = await self._upload_images(page, image_paths)
                    if not images_uploaded:
                        await self._progress("图片上传失败，请手动添加图片")
                else:
                    await self._progress("图片生成失败，请手动上传图片")
            else:
                await self._progress("未配置图片生成，请手动上传图片")
        except Exception as e:
            logger.warning("Douyin image generation/upload failed: %s", e)
            await self._progress(f"图片处理异常：{e}，请手动上传")
        finally:
            if tmp_dir and tmp_dir.exists():
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception as e:
                    logger.warning("Douyin tmp cleanup failed: %s", e)

        await self._shot(page, "douyin_03_images_uploaded.png")

        # 4. 如果图片自动上传失败，等待用户手动上传图片
        #    上传后页面会跳转到 post/image 页，标题输入框会出现
        if not images_uploaded:
            await self._progress("请在浏览器中手动上传图片，上传后系统将自动填写标题和内容...")
            # 等待用户手动上传（最长等待 120 秒）
            manual_uploaded = await self._wait_for_title_input(page, timeout=120)
            if manual_uploaded:
                logger.info("Douyin: user manually uploaded images, title input appeared")
                await self._shot(page, "douyin_03b_manual_upload.png")
            else:
                await self._progress("等待图片上传超时，请确保已上传图片后手动填写标题和内容")
                await self._shot(page, "douyin_03c_timeout.png")

        # 5. 填写标题（在 post/image 页面）
        title_filled = await self._fill_title(page, title)
        if not title_filled:
            await self._progress("未能自动填写标题，请手动填写标题")
        await self._shot(page, "douyin_04_title_filled.png")

        # 6. 填写正文
        content_filled = await self._fill_content(page, content, title)
        if not content_filled:
            await self._progress("未能自动填写正文，请手动填写内容")
        await self._shot(page, "douyin_05_content_filled.png")

        await random_delay(3, 5)

        await self._progress("内容已填好，请在浏览器窗口检查后手动点「发布」")
        await self._shot(page, "douyin_06_final.png")

        # 7. 等待用户发布
        #    发布成功后页面会跳转到 /content/manage 页面
        published = False
        for _ in range(PUBLISH_MANUAL_TIMEOUT):
            await asyncio.sleep(1)
            current_url = page.url
            # 发布成功后跳转到内容管理页
            if MANAGE_URL_PATTERN in current_url.lower():
                published = True
                break
            try:
                toast = await page.query_selector("[class*='success'], .toast, .notification")
                if toast:
                    text = await toast.text_content()
                    if text and "成功" in text:
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
            success=False,
            platform=self.platform_name,
            article_title=title,
            published_url="",
            error_message="内容已填好但未发布：请在浏览器窗口手动点「发布」",
        )
