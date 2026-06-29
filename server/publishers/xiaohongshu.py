"""小红书发布 — Playwright browser automation."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from pathlib import Path

from .base import BrowserPublisher, PublishResult, NeedLoginError, random_delay
from .image_archive import archive_key, try_read_archive, write_archive
from config import PUBLISH_MANUAL_TIMEOUT, UPLOAD_DIR

logger = logging.getLogger(__name__)

DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug_screenshots"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# 临时图片目录（生成后上传，发布结束清理）
TMP_IMG_DIR = Path(UPLOAD_DIR) / "xhs_tmp"
TMP_IMG_DIR.mkdir(parents=True, exist_ok=True)

# 文生图限流：DashScope qwen-image 并发/QPS 较低，全量并行易触发
# Throttling.RateQuota。这里用「限制并发 + 每张间隔」控制节奏，
# 失败的图片自动重试一次。可通过环境变量 XHS_IMAGE_CONCURRENCY /
# XHS_IMAGE_INTERVAL_SECONDS 调整。
XHS_IMAGE_CONCURRENCY = int(os.getenv("XHS_IMAGE_CONCURRENCY", "1"))
XHS_IMAGE_INTERVAL_SECONDS = float(os.getenv("XHS_IMAGE_INTERVAL_SECONDS", "3"))
XHS_IMAGE_MAX = int(os.getenv("XHS_IMAGE_MAX", "9"))


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

    async def _shot(self, page, name: str) -> None:
        """保存调试截图，失败不影响主流程。"""
        try:
            await page.screenshot(path=str(DEBUG_DIR / name), full_page=True)
            logger.info("XHS debug screenshot saved: %s", name)
        except Exception as e:
            logger.warning("XHS screenshot %s failed: %s", name, e)

    async def _click_image_text_tab(self, page) -> bool:
        """切换到「上传图文」tab，跳过隐藏/离屏副本，返回是否切换成功。

        小红书每个 tab 都有多个 DOM 副本：
          - 插件注入的 aria-hidden="true" + opacity:1e-05 副本（pointerEvents:auto，
            会拦截/干扰点击）
          - left:-9999px 的测量副本（离屏，Playwright 点击会报 outside of viewport）
          - 真正可见可点击的实例（position:relative, opacity:1）

        实测：用 Playwright locator 点击真实实例会被插件副本干扰导致失败，
        且插件副本移除后会立即重新注入（在两次 JS 调用之间）。
        唯一可靠方案：在单次 JS evaluate 内原子地"移除干扰副本 + 立即 click
        position:relative 真实实例"，避免插件重新注入的时序窗口。
        """
        try:
            result = await page.evaluate(
                """() => {
                    // 1. 移除插件副本与离屏测量副本
                    document.querySelectorAll('.creator-tab[aria-hidden="true"]').forEach(e => e.remove());
                    document.querySelectorAll('.creator-tab[style*="-9999px"]').forEach(e => e.remove());
                    // 2. 找到 position:relative 的真实实例并点击（移除后立即点击，避免插件重新注入）
                    const tabs = Array.from(document.querySelectorAll('.creator-tab'));
                    const target = tabs.find(el => {
                        if (!(el.textContent || '').includes('上传图文')) return false;
                        return getComputedStyle(el).position === 'relative';
                    });
                    if (!target) return {clicked: false, reason: 'no relative instance'};
                    target.click();
                    return {clicked: true};
                }"""
            )
            logger.info("XHS: 原子切换 tab 结果: %s", result)
            if not result.get("clicked"):
                logger.warning("XHS: 未找到上传图文真实实例: %s", result.get("reason"))
                return False

            await page.wait_for_load_state("networkidle", timeout=10000)
            await random_delay(2, 4)

            # 校验是否真的切换成功
            active = await page.evaluate(
                """() => {
                    const a = document.querySelector('.creator-tab.active');
                    return a ? (a.textContent || '').trim() : '';
                }"""
            )
            logger.info("XHS: 切换后 active tab=%s", active)
            if active and "图文" in active:
                return True
            logger.warning("XHS: 点击后 active 仍为 %s，切换可能未生效", active)
            await self._shot(page, "xhs_tab_switch_fail.png")
            return False
        except Exception as e:
            logger.warning("XHS: 切换到上传图文 tab 失败: %s", e)
            await self._shot(page, "xhs_tab_switch_fail.png")
            return False

    async def _generate_one(
        self, gen, kind: str, idx: int, args, tmp_dir: Path,
        archive_path: Path | None = None,
    ) -> Path | None:
        """生成单张图片（带存档复用 + 一次重试 + 限流间隔），返回文件路径或 None。

        kind: 'cover' 或 'inline'；args: 生成方法所需入参。
        archive_path: 存档路径。XHS_IMAGE_ARCHIVE 且存档存在时直接复用（省去
        DashScope 调用）；否则调文生图生成，成功后写一份到存档供下次复用。
        调用方已通过 Semaphore 限制并发。
        """
        out_name = "cover_0.jpg" if kind == "cover" else f"inline_{idx}.jpg"
        out_path = tmp_dir / out_name

        # 1) 存档复用
        if try_read_archive(archive_path, out_path):
            await self._progress(f"复用已存档的{kind}图（跳过生成）")
            return out_path

        # 2) 调文生图生成
        async def _gen_once() -> bytes:
            coro = gen.generate_cover_image(*args) if kind == "cover" else gen.generate_section_image(*args)
            return await coro

        try:
            data = await _gen_once()
            out_path.write_bytes(data)
            write_archive(archive_path, data)
            logger.info("XHS: %s图生成成功 %s", kind, out_path)
            return out_path
        except Exception as e:
            logger.warning("XHS: %s图第 1 次生成失败: %s，3 秒后重试一次", kind, e)
            await asyncio.sleep(3)
            try:
                data = await _gen_once()
                out_path.write_bytes(data)
                write_archive(archive_path, data)
                logger.info("XHS: %s图重试成功 %s", kind, out_path)
                return out_path
            except Exception as e2:
                logger.warning("XHS: %s图重试仍失败: %s", kind, e2)
                return None

    async def _generate_image_files(
        self, gen, title: str, content: str,
        generate_cover: bool, generate_inline_images: bool,
        tmp_dir: Path,
    ) -> list[Path]:
        """生成封面 + 正文图，写入临时目录，返回路径列表（封面在前）。

        DashScope 文生图并发/QPS 较低，全量并行会触发 Throttling.RateQuota，
        因此用「限制并发(XHS_IMAGE_CONCURRENCY) + 每张之间间隔
        (XHS_IMAGE_INTERVAL_SECONDS)」控速，单张失败重试一次后跳过。
        正文图数量上限 XHS_IMAGE_MAX。
        """
        # 组装待生成任务队列：(kind, idx, args, archive_path)
        jobs: list[tuple[str, int, tuple, Path]] = []
        if generate_cover:
            jobs.append(("cover", 0, (title, content), archive_key("cover", title)))
        if generate_inline_images:
            try:
                from core.image_generator import split_by_headings
                sections = split_by_headings(content)
                # 小红书图文最多 9 张，封面占 1 张时正文最多 8 张
                max_inline = XHS_IMAGE_MAX - 1 if generate_cover else XHS_IMAGE_MAX
                for i, s in enumerate(sections[:max_inline], start=1):
                    if s.title:
                        key = archive_key("inline", s.title, s.text)
                    else:
                        # 空标题时加索引避免不同空章节冲突
                        key = archive_key("inline", s.text[:200], str(i))
                    jobs.append(("inline", i, (s.title, s.text), key))
            except Exception as e:
                logger.warning("XHS: 正文分节失败: %s", e)

        if not jobs:
            return []

        sem = asyncio.Semaphore(XHS_IMAGE_CONCURRENCY)
        paths: list[Path] = []

        async def run_job(idx_in_queue: int, job: tuple[str, int, tuple, Path]) -> Path | None:
            async with sem:
                if idx_in_queue > 0:
                    await asyncio.sleep(XHS_IMAGE_INTERVAL_SECONDS)
                kind, _jidx, args, archive_path = job
                return await self._generate_one(gen, kind, _jidx, args, tmp_dir, archive_path)

        results = await asyncio.gather(
            *(run_job(i, j) for i, j in enumerate(jobs)),
            return_exceptions=True,
        )
        # 封面在前：cover 一定排在队列首，正文图随后；按 jobs 顺序保留成功的
        for r in results:
            if isinstance(r, Exception):
                logger.warning("XHS: 某张图片生成异常，跳过: %s", r)
            elif r is not None:
                paths.append(r)
        logger.info("XHS: 图片生成完成，共成功 %d 张（含封面）", len(paths))
        return paths

    async def _upload_images(self, page, image_paths: list[Path]) -> bool:
        """把图片上传到小红书图文区。优先直接 file input，降级用 filechooser。

        实测：图文 tab 下存在可见的 <input type="file" class="upload-input"
        accept=".jpg,.jpeg,.png,.webp">，可直接 set_input_files 上传多张，最可靠。
        """
        if not image_paths:
            return False

        str_paths = [str(p) for p in image_paths]

        # 路径1（首选）：直接对 file input 调 set_input_files（支持多文件）
        try:
            file_input = page.locator("input.upload-input[type='file']").first
            await file_input.wait_for(timeout=8000)
            await file_input.set_input_files(str_paths)
            logger.info("XHS: 通过 file input 上传 %d 张图片", len(str_paths))
            await random_delay(2, 4)
            return True
        except Exception as e:
            logger.warning("XHS: file input 上传失败: %s，尝试 filechooser 降级", e)

        # 路径2（兜底）：点击「上传图片」按钮触发文件选择器
        try:
            trigger = page.locator("button.upload-button, .upload-btn, .upload-plus, [class*='upload-wrapper']").filter(visible=True).first
            await trigger.wait_for(timeout=8000)
            async with page.expect_file_chooser(timeout=10000) as fc_info:
                await trigger.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(str_paths)
            logger.info("XHS: 通过 filechooser 上传 %d 张图片", len(str_paths))
            await random_delay(2, 4)
            return True
        except Exception as e:
            logger.warning("XHS: filechooser 上传失败: %s", e)
            await self._shot(page, "xhs_upload_fail.png")
            return False

    async def _do_publish(self, page, title: str, content: str, **kwargs) -> PublishResult:
        # 小红书「上传图文」必须配图，图文发布默认生成封面 + 正文图（除非前端明确传 false）。
        generate_cover = kwargs.get("generate_cover", True)
        generate_inline_images = kwargs.get("generate_inline_images", True)

        await page.goto(self.publish_url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        await random_delay(2, 4)

        if "login" in page.url.lower():
            raise NeedLoginError("小红书登录已过期，请重新扫码登录")

        await self._shot(page, "xhs_01_publish_page.png")
        logger.info("XHS: publish page ready, url=%s", page.url)

        # 1. 切换到「上传图文」tab
        switched = await self._click_image_text_tab(page)
        await self._shot(page, "xhs_02_image_text_tab.png")
        if not switched:
            await self._progress("未能切换到「上传图文」tab，请手动切换并上传图片")

        # 2. 生成图片并上传
        image_paths: list[Path] = []
        tmp_dir: Path | None = None
        try:
            from config import IMAGE_GEN_ENABLED, DASHSCOPE_API_KEY, IMAGE_GEN_MODEL
            if IMAGE_GEN_ENABLED and DASHSCOPE_API_KEY:
                from core.image_generator import ImageGenerator
                gen = ImageGenerator(DASHSCOPE_API_KEY, IMAGE_GEN_MODEL)

                total_inline = 0
                if generate_inline_images:
                    try:
                        from core.image_generator import split_by_headings
                        total_inline = len(split_by_headings(content))
                    except Exception:
                        pass
                suffix = f" + {total_inline} 张正文图" if generate_inline_images else ""
                await self._progress(f"正在生成 1 张封面图{suffix}...")

                tmp_dir = TMP_IMG_DIR / uuid.uuid4().hex[:12]
                tmp_dir.mkdir(parents=True, exist_ok=True)
                image_paths = await self._generate_image_files(
                    gen, title, content, generate_cover, generate_inline_images, tmp_dir,
                )
                logger.info("XHS: 共生成 %d 张图片待上传", len(image_paths))

                if image_paths:
                    await self._progress(f"正在上传 {len(image_paths)} 张图片到小红书...")
                    uploaded = await self._upload_images(page, image_paths)
                    if not uploaded:
                        await self._progress("图片上传失败，请手动添加图片")
                else:
                    await self._progress("图片生成失败，请手动上传图片")
            else:
                logger.warning("XHS: 图片生成未启用或无 DASHSCOPE_API_KEY，跳过图片")
                await self._progress("未配置图片生成，请手动上传图片")
        except Exception as e:
            logger.warning("XHS: 图片生成/上传流程异常: %s", e)
            await self._progress(f"图片处理异常：{e}，请手动上传图片")
        finally:
            # 清理临时图片目录
            if tmp_dir and tmp_dir.exists():
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    logger.info("XHS: 已清理临时图片目录 %s", tmp_dir)
                except Exception as e:
                    logger.warning("XHS: 清理临时目录失败: %s", e)

        await self._shot(page, "xhs_03_images_uploaded.png")

        # 3. 写标题（图文 tab 上传图片后才会渲染标题输入框；标题框是
        # .c-input_inner div 内的 <input type="text">，不能 fill 到 div 容器）。
        title_input = None
        title_sels = [
            "input[placeholder*='填写']",
            ".c-input_inner input[type='text']",
            ".d-input input[type='text']",
        ]
        for s in title_sels:
            try:
                await page.wait_for_selector(s, timeout=10000)
                title_input = await page.query_selector(s)
                if title_input:
                    break
            except Exception:
                continue
        if title_input:
            await title_input.click()
            await random_delay(0.5, 1)
            await title_input.fill(title[:20])
            await random_delay(1, 2)
            logger.info("XHS: 标题已填入（截断到20字）")
        else:
            logger.warning("XHS: 未找到标题输入框（可能未上传图片，小红书要求先上传图片才出现标题框）")
        await self._shot(page, "xhs_04_title_filled.png")

        # 4. 写正文（图文 tab 用 TipTap/ProseMirror 富文本编辑器，
        # 选择器为 .ProseMirror，contenteditable=true）。
        editor = None
        editor_sels = [".ProseMirror", ".tiptap.ProseMirror", ".editor-content [contenteditable='true']"]
        for s in editor_sels:
            try:
                await page.wait_for_selector(s, timeout=10000)
                editor = await page.query_selector(s)
                if editor:
                    break
            except Exception:
                continue
        if editor:
            await editor.click()
            await random_delay(0.5, 1)
            plain_text = content.replace("**", "").replace("*", "").replace("#", "").replace(">", "")
            paragraphs = [p.strip() for p in plain_text.split("\n") if p.strip()]
            for para in paragraphs[:50]:
                await page.keyboard.type(para)
                await page.keyboard.press("Enter")
                await random_delay(0.3, 0.8)
            logger.info("XHS: 正文已填入，共 %d 段", len(paragraphs[:50]))
        else:
            logger.warning("XHS: 未找到正文编辑器")
        await self._shot(page, "xhs_05_content_filled.png")

        await random_delay(3, 5)

        await self._progress("图文已填好，请在浏览器窗口检查后手动点「发布」")
        await self._shot(page, "xhs_06_final.png")

        published = False
        for _ in range(PUBLISH_MANUAL_TIMEOUT):
            await asyncio.sleep(1)
            current_url = page.url
            if "/publish/publish" not in current_url:
                published = True
                break

        if published:
            return PublishResult(
                success=True,
                platform=self.platform_name,
                article_title=title,
                published_url="https://www.xiaohongshu.com/user/profile/self",
            )
        return PublishResult(
            success=True,
            platform=self.platform_name,
            article_title=title,
            published_url="",
            error_message="内容已填好但未发布：请在浏览器窗口手动点「发布」",
        )
