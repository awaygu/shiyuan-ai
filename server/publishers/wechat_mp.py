"""WeChat Official Account publisher — draft box API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx

from core.image_generator import Section

from .base import BasePublisher, PublishResult
from .image_archive import archive_key, try_read_archive_bytes, write_archive

logger = logging.getLogger(__name__)

WECHAT_API_BASE = "https://api.weixin.qq.com"

WECHAT_TOKEN_ERRORS = {40001, 40014, 42001}
WECHAT_IP_WHITELIST_ERROR = 40164


class WechatApiError(Exception):
    def __init__(self, errcode: int, errmsg: str):
        self.errcode = errcode
        self.errmsg = errmsg
        super().__init__(f"WeChat API error {errcode}: {errmsg}")

    @property
    def is_token_error(self) -> bool:
        return self.errcode in WECHAT_TOKEN_ERRORS


class WechatTokenManager:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token = ""
        self._expires_at: float = 0

    async def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 300:
            return self._token
        return await self.refresh_token()

    async def refresh_token(self) -> str:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{WECHAT_API_BASE}/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self.app_id,
                    "secret": self.app_secret,
                },
            )
            data = resp.json()
            if "access_token" not in data:
                errcode = data.get("errcode", 0)
                errmsg = data.get("errmsg", "")
                raise WechatApiError(errcode, errmsg)
            self._token = data["access_token"]
            self._expires_at = time.time() + data.get("expires_in", 7200)
            logger.info("WeChat access_token refreshed, expires_in=%s", data.get("expires_in"))
            return self._token

    async def upload_image(self, image_url: str) -> str:
        token = await self.get_token()
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            img_resp = await client.get(
                image_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            img_resp.raise_for_status()
            content_type = img_resp.headers.get("content-type", "image/jpeg")
            ext = "jpg" if "jpeg" in content_type or "jpg" in content_type else "png"
            filename = f"image.{ext}"

            upload_resp = await client.post(
                f"{WECHAT_API_BASE}/cgi-bin/media/uploadimg",
                params={"access_token": token},
                files={"media": (filename, img_resp.content, content_type)},
            )
            data = upload_resp.json()
            if "url" not in data:
                raise WechatApiError(data.get("errcode", 0), data.get("errmsg", "upload failed"))
            return data["url"]

    async def upload_image_from_bytes(self, image_bytes: bytes, content_type: str = "image/png") -> str:
        token = await self.get_token()
        ext = "png" if "png" in content_type else "jpg"
        filename = f"image.{ext}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            upload_resp = await client.post(
                f"{WECHAT_API_BASE}/cgi-bin/media/uploadimg",
                params={"access_token": token},
                files={"media": (filename, image_bytes, content_type)},
            )
            data = upload_resp.json()
            if "url" not in data:
                raise WechatApiError(data.get("errcode", 0), data.get("errmsg", "upload from bytes failed"))
            return data["url"]


def markdown_to_wechat_html(text: str) -> str:
    lines = text.split("\n")
    html_parts: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            level = min(len(heading_match.group(1)), 4)
            title = heading_match.group(2)
            html_parts.append(f"<h{level}>{_esc(title)}</h{level}>")
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{_esc(stripped[2:])}</li>")
            continue

        if re.match(r"^\d+\.\s+", stripped):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            content = re.sub(r"^\d+\.\s+", "", stripped)
            html_parts.append(f"<li>{_esc(content)}</li>")
            continue

        if in_list:
            html_parts.append("</ul>")
            in_list = False

        if stripped.startswith("> "):
            html_parts.append(f"<blockquote>{_esc(stripped[2:])}</blockquote>")
            continue

        if stripped == "---" or stripped == "***":
            html_parts.append("<hr/>")
            continue

        bold = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
        em = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bold)
        html_parts.append(f"<p>{em}</p>")

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class WechatMpPublisher(BasePublisher):
    def __init__(self, app_id: str = "", app_secret: str = ""):
        super().__init__("wechat_mp")
        from config import WECHAT_APP_ID, WECHAT_APP_SECRET

        self.app_id = app_id or WECHAT_APP_ID
        self.app_secret = app_secret or WECHAT_APP_SECRET
        self.token_manager = WechatTokenManager(self.app_id, self.app_secret)

    async def check_login(self) -> bool:
        if not self.app_id or not self.app_secret:
            return False
        try:
            await self.token_manager.get_token()
            return True
        except WechatApiError as e:
            if e.errcode == WECHAT_IP_WHITELIST_ERROR:
                logger.warning("WeChat IP not in whitelist: %s", e.errmsg)
            return False
        except Exception:
            return False

    async def do_login(self) -> bool:
        if not self.app_id or not self.app_secret:
            raise WechatApiError(-1, "未配置 WECHAT_APP_ID 或 WECHAT_APP_SECRET，请在 .env 中设置")
        try:
            await self.token_manager.refresh_token()
            return True
        except WechatApiError:
            raise
        except Exception as e:
            raise WechatApiError(-1, f"获取 access_token 失败: {e}")

    async def upload_thumb(self, token: str, image_bytes: bytes | None = None) -> str:
        from io import BytesIO

        from PIL import Image

        if image_bytes is None:
            img = Image.new("RGB", (900, 383), color=(99, 102, 241))
            buf = BytesIO()
            img.save(buf, format="JPEG")
            buf.seek(0)
            image_bytes = buf.read()

        async with httpx.AsyncClient(timeout=30.0) as client:
            upload_resp = await client.post(
                f"{WECHAT_API_BASE}/cgi-bin/material/add_material",
                params={"access_token": token, "type": "image"},
                files={"media": ("thumb.jpg", image_bytes, "image/jpeg")},
            )
            data = upload_resp.json()
            if "media_id" not in data:
                raise WechatApiError(data.get("errcode", 0), data.get("errmsg", "thumb upload failed"))
            return data["media_id"]

    async def publish(self, title: str, content: str, **kwargs) -> PublishResult:
        generate_cover = kwargs.get("generate_cover", True)
        generate_inline_images = kwargs.get("generate_inline_images", False)
        on_progress = kwargs.get("on_progress")

        async def _progress(msg: str):
            if on_progress:
                await on_progress(msg)

        if not self.app_id or not self.app_secret:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                article_title=title,
                need_login=True,
                error_message="WECHAT_APP_ID or WECHAT_APP_SECRET not configured",
            )

        await _progress("正在获取 access_token...")
        try:
            token = await self.token_manager.get_token()
        except WechatApiError as e:
            need_login = e.is_token_error
            return PublishResult(
                success=False,
                platform=self.platform_name,
                article_title=title,
                need_login=need_login,
                error_message=f"WeChat API error {e.errcode}: {e.errmsg}",
            )
        except Exception as e:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                article_title=title,
                need_login=False,
                error_message=f"Failed to get access_token: {e}",
            )

        thumb_media_id = ""
        if generate_cover:
            try:
                from config import DASHSCOPE_API_KEY, IMAGE_GEN_ENABLED, IMAGE_GEN_MODEL

                if IMAGE_GEN_ENABLED and DASHSCOPE_API_KEY:
                    cover_key = archive_key("cover", title)
                    cover_bytes = try_read_archive_bytes(cover_key)
                    if cover_bytes:
                        await _progress("复用已存档的封面图...")
                    else:
                        from core.image_generator import ImageGenerator

                        gen = ImageGenerator(DASHSCOPE_API_KEY, IMAGE_GEN_MODEL)
                        await _progress("正在生成 AI 封面图...")
                        cover_bytes = await gen.generate_cover_image(title, content)
                        write_archive(cover_key, cover_bytes)
                    await _progress("正在上传封面图到微信...")
                    thumb_media_id = await self.upload_thumb(token, image_bytes=cover_bytes)
                    logger.info("AI cover image uploaded: media_id=%s", thumb_media_id)
                else:
                    logger.info("Image generation disabled or no API key, using placeholder cover")
                    thumb_media_id = await self.upload_thumb(token)
            except Exception as e:
                logger.warning("AI cover image generation failed: %s, using placeholder", e)
                thumb_media_id = await self.upload_thumb(token)
        else:
            thumb_media_id = await self.upload_thumb(token)

        await _progress("正在转换文章格式...")
        html_content = markdown_to_wechat_html(content)

        img_pattern = re.compile(r"!\[.*?\]\((https?://[^\s)]+)\)")
        img_urls = img_pattern.findall(content)
        if img_urls:
            await _progress("正在转存文章图片...")
        for img_url in img_urls:
            try:
                wechat_url = await self.token_manager.upload_image(img_url)
                html_content = html_content.replace(img_url, wechat_url)
            except Exception as e:
                logger.warning("Failed to upload image %s: %s", img_url, e)

        if generate_inline_images:
            try:
                from config import DASHSCOPE_API_KEY, IMAGE_GEN_ENABLED, IMAGE_GEN_MODEL

                if IMAGE_GEN_ENABLED and DASHSCOPE_API_KEY:
                    from core.image_generator import ImageGenerator, split_by_headings

                    gen = ImageGenerator(DASHSCOPE_API_KEY, IMAGE_GEN_MODEL)
                    sections = split_by_headings(content)
                    if sections:
                        # 先查存档，未命中的才生成
                        images: list[bytes | Exception] = []
                        to_generate: list[tuple[int, Section]] = []
                        for i, s in enumerate(sections):
                            inline_key = archive_key("inline", s.title or "", s.text)
                            cached = try_read_archive_bytes(inline_key)
                            if cached:
                                images.append(cached)
                            else:
                                images.append(None)  # placeholder
                                to_generate.append((i, s, inline_key))

                        if to_generate:
                            await _progress(
                                f"正在生成 {len(to_generate)} 张正文插图（{len(sections)} 节，复用 {len(sections) - len(to_generate)} 张）..."
                            )
                            gen_tasks = [gen.generate_section_image(s.title, s.text) for _, s, _ in to_generate]
                            gen_results = await asyncio.gather(*gen_tasks, return_exceptions=True)
                            for (idx, _, key), result in zip(to_generate, gen_results):
                                if isinstance(result, Exception):
                                    images[idx] = result
                                    logger.warning("Section image generation failed: %s", result)
                                else:
                                    images[idx] = result
                                    write_archive(key, result)
                        else:
                            await _progress(f"复用全部 {len(sections)} 张正文插图...")

                        heading_pattern = re.compile(r"^(<h[23]>.*?</h[23]>)", re.MULTILINE)
                        parts = heading_pattern.split(html_content)
                        section_idx = 0
                        new_parts: list[str] = []
                        for part in parts:
                            new_parts.append(part)
                            if heading_pattern.match(part) and section_idx < len(images):
                                img = images[section_idx]
                                if isinstance(img, bytes):
                                    try:
                                        wechat_url = await self.token_manager.upload_image_from_bytes(img)
                                        new_parts.append(
                                            f'<p><img src="{wechat_url}" style="max-width:100%;border-radius:8px;margin:8px 0;"/></p>'
                                        )
                                    except Exception as e:
                                        logger.warning("Failed to upload section image: %s", e)
                                section_idx += 1
                        html_content = "".join(new_parts)
            except Exception as e:
                logger.warning("AI inline images generation failed: %s", e)

        digest = content[:120].replace("\n", " ").strip()

        clean_title = re.sub(r"[#*>\-]", "", title).strip()
        clean_title = re.sub(r"\s+", " ", clean_title)
        encoded = clean_title.encode("utf-8")
        if len(encoded) > 64:
            while len(encoded) > 61:
                clean_title = clean_title[:-1]
                encoded = clean_title.encode("utf-8")
            clean_title += "…"

        await _progress("正在创建微信草稿...")

        draft_body = {
            "articles": [
                {
                    "title": clean_title,
                    "content": html_content,
                    "digest": digest,
                    "thumb_media_id": thumb_media_id,
                }
            ]
        }
        body_bytes = json.dumps(draft_body, ensure_ascii=False).encode("utf-8")
        logger.info(
            "WeChat draft body title: repr=%s, len=%d, utf8_bytes=%d, json_body_bytes=%d",
            repr(clean_title),
            len(clean_title),
            len(clean_title.encode("utf-8")),
            len(body_bytes),
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{WECHAT_API_BASE}/cgi-bin/draft/add",
                params={"access_token": token},
                content=body_bytes,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            data = resp.json()

        logger.info("WeChat draft/add response: %s", json.dumps(data, ensure_ascii=False))

        if "media_id" not in data:
            errcode = data.get("errcode", 0)
            errmsg = data.get("errmsg", "")
            need_login = errcode in (40001, 40014, 42001)
            return PublishResult(
                success=False,
                platform=self.platform_name,
                article_title=title,
                need_login=need_login,
                error_message=f"WeChat API error {errcode}: {errmsg}",
            )

        media_id = data["media_id"]
        logger.info("WeChat draft created: media_id=%s", media_id)

        return PublishResult(
            success=True,
            platform=self.platform_name,
            article_title=title,
            published_url="https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&action=list_card",
            extra={"media_id": media_id},
        )
