"""AI image generation module using DashScope qwen-image-2.0-pro.

Generates cover images and inline illustrations for articles
published to WeChat Official Account.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import httpx
from PIL import Image

from core.langsmith_utils import traceable

logger = logging.getLogger(__name__)

DASHSCOPE_GEN_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

DEFAULT_NEGATIVE_PROMPT = "低分辨率，低画质，画面具有AI感，构图混乱，文字模糊，扭曲，水印，logo，字母"


@dataclass
class Section:
    title: str
    text: str


class ImageGenerator:
    def __init__(self, api_key: str, model: str = "qwen-image-2.0-pro"):
        self.api_key = api_key
        self.model = model

    async def generate_image(
        self,
        prompt: str,
        size: str = "2048*868",
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
        n: int = 1,
        prompt_extend: bool = True,
        retries: int = 2,
    ) -> bytes:
        for attempt in range(1, retries + 2):
            try:
                return await self._call_api(prompt, size, negative_prompt, n, prompt_extend)
            except Exception as e:
                logger.warning("Image generation attempt %d failed: %s", attempt, e)
                if attempt > retries:
                    raise

    @traceable(
        "image: dashscope_generate",
        tags=["image_gen"],
        metadata={"model": "qwen-image-2.0-pro"},
    )
    async def _call_api(
        self,
        prompt: str,
        size: str,
        negative_prompt: str,
        n: int,
        prompt_extend: bool,
    ) -> bytes:
        body = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ]
            },
            "parameters": {
                "size": size,
                "n": n,
                "prompt_extend": prompt_extend,
                "negative_prompt": negative_prompt,
                "watermark": False,
            },
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                DASHSCOPE_GEN_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            data = resp.json()

        if "code" in data and data.get("code"):
            raise RuntimeError(f"DashScope error {data.get('code')}: {data.get('message')}")

        choices = data.get("output", {}).get("choices", [])
        if not choices:
            raise RuntimeError("No image generated in response")

        content = choices[0].get("message", {}).get("content", [])
        image_url = None
        for item in content:
            if "image" in item:
                image_url = item["image"]
                break

        if not image_url:
            raise RuntimeError("No image URL in response")

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            return img_resp.content

    async def extract_image_prompt(
        self,
        title: str,
        digest: str,
        context: str = "cover",
    ) -> str:
        from prompts import IMAGE_PROMPT_COVER, IMAGE_PROMPT_INLINE

        if context == "cover":
            template = IMAGE_PROMPT_COVER
            text = template.format(title=title, digest=digest[:300])
        else:
            template = IMAGE_PROMPT_INLINE
            text = template.format(section_title=title, section_digest=digest[:300])

        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, TEMPERATURE_ANALYZE
        from core.style_manager import prompt_manager

        llm = ChatOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            temperature=TEMPERATURE_ANALYZE,
            max_tokens=300,
        )
        prompt_text = ChatPromptTemplate.from_messages(
            [
                ("system", prompt_manager.image_prompt_writer_system_prompt),
                ("human", text),
            ]
        )
        chain = prompt_text | llm
        result = await chain.ainvoke({})
        return result.content.strip().strip('"').strip("'")

    async def generate_cover_image(self, title: str, content: str) -> bytes:
        digest = content[:300]
        prompt = await self.extract_image_prompt(title, digest, "cover")
        logger.info("Cover image prompt: %s", prompt)
        img_bytes = await self.generate_image(prompt, size="2048*868")
        return self._crop_cover(img_bytes)

    async def generate_section_image(self, section_title: str, section_text: str) -> bytes:
        digest = section_text[:300]
        prompt = await self.extract_image_prompt(section_title, digest, "inline")
        logger.info("Section image prompt [%s]: %s", section_title, prompt)
        return await self.generate_image(prompt, size="1536*1024")

    @staticmethod
    def _crop_cover(img_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        target_ratio = 900 / 383
        current_ratio = w / h
        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        elif current_ratio < target_ratio:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))
        img = img.resize((900, 383), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        buf.seek(0)
        return buf.read()


def split_by_headings(markdown_text: str) -> list[Section]:
    sections: list[Section] = []
    current_title = ""
    current_lines: list[str] = []

    for line in markdown_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            if current_title or current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append(Section(title=current_title, text=text))
            current_title = stripped.lstrip("# ").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_title or current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(Section(title=current_title, text=text))

    return sections
