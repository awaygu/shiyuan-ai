"""Document chunker: split text into ~500-char chunks at sentence boundaries, with page tracking."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from config import KB_CHUNK_OVERLAP, KB_CHUNK_SIZE

SENTENCE_END_RE = re.compile(r"([。！？；\.\!\?;])")


@dataclass
class Chunk:
    chunk_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    doc_id: str = ""
    chunk_index: int = 0
    text: str = ""
    page: int = 0


class TextChunker:
    def __init__(
        self,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ):
        self.chunk_size = chunk_size or KB_CHUNK_SIZE
        self.overlap = overlap or KB_CHUNK_OVERLAP

    def chunk(self, text: str, doc_id: str = "") -> list[Chunk]:
        if not text.strip():
            return []

        sentences = self._split_sentences(text)
        chunks: list[Chunk] = []
        current_text = ""
        idx = 0

        for sent in sentences:
            if len(current_text) + len(sent) > self.chunk_size and current_text:
                chunks.append(
                    Chunk(
                        doc_id=doc_id,
                        chunk_index=idx,
                        text=current_text.strip(),
                        page=0,
                    )
                )
                idx += 1
                if self.overlap > 0 and len(current_text) > self.overlap:
                    current_text = current_text[-self.overlap :] + sent
                else:
                    current_text = sent
            else:
                current_text += sent

        if current_text.strip():
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    chunk_index=idx,
                    text=current_text.strip(),
                    page=0,
                )
            )

        return chunks

    def chunk_with_pages(self, pages: list, doc_id: str = "") -> list[Chunk]:
        if not pages:
            return []

        all_sentences: list[tuple[str, int]] = []
        for p in pages:
            sents = self._split_sentences(p.text)
            for s in sents:
                all_sentences.append((s, p.page))

        chunks: list[Chunk] = []
        current_text = ""
        current_pages: set[int] = set()
        idx = 0

        for sent, page in all_sentences:
            if len(current_text) + len(sent) > self.chunk_size and current_text:
                primary_page = min(current_pages) if current_pages else 0
                chunks.append(
                    Chunk(
                        doc_id=doc_id,
                        chunk_index=idx,
                        text=current_text.strip(),
                        page=primary_page,
                    )
                )
                idx += 1
                if self.overlap > 0 and len(current_text) > self.overlap:
                    overlap_text = current_text[-self.overlap :]
                    current_text = overlap_text + sent
                    current_pages = {page}
                else:
                    current_text = sent
                    current_pages = {page}
            else:
                current_text += sent
                current_pages.add(page)

        if current_text.strip():
            primary_page = min(current_pages) if current_pages else 0
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    chunk_index=idx,
                    text=current_text.strip(),
                    page=primary_page,
                )
            )

        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        parts = SENTENCE_END_RE.split(text)
        sentences: list[str] = []
        buf = ""
        for part in parts:
            buf += part
            if SENTENCE_END_RE.match(part):
                sentences.append(buf)
                buf = ""
        if buf.strip():
            sentences.append(buf)
        return [s for s in sentences if s.strip()]
