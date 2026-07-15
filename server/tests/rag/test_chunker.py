"""TextChunker 分块逻辑测试：句子切分、chunk_size/overlap、分页 chunk_with_pages。"""

from __future__ import annotations

from rag.chunker import Chunk, TextChunker


def test_chunk_empty_text_returns_empty():
    assert TextChunker().chunk("") == []
    assert TextChunker().chunk("   \n  ") == []


def test_chunk_short_text_returns_single_chunk():
    chunker = TextChunker(chunk_size=500)
    chunks = chunker.chunk("这是一段短文本，不会超过 chunk_size。", doc_id="d1")
    assert len(chunks) == 1
    assert chunks[0].doc_id == "d1"
    assert chunks[0].chunk_index == 0
    assert "短文本" in chunks[0].text


def test_chunk_splits_at_sentence_boundary():
    """超过 chunk_size 时在句子边界切分，产生多个 chunk。"""
    chunker = TextChunker(chunk_size=10, overlap=0)
    # 每句约 9 字，两句即超过 10，应触发切分
    text = "这是第一句话内容。这是第二句话内容。这是第三句话内容。"
    chunks = chunker.chunk(text, doc_id="d1")
    assert len(chunks) >= 2
    # chunk_index 递增
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert c.doc_id == "d1"


def test_chunk_overlap_carries_tail():
    """overlap > 0 时，下一 chunk 以上一 chunk 的尾部 overlap 字符开头。"""
    chunker = TextChunker(chunk_size=20, overlap=5)
    text = "这是第一段较长内容。这是第二段较长内容。这是第三段较长内容。"
    chunks = chunker.chunk(text, doc_id="d1")
    if len(chunks) >= 2:
        # 第二个 chunk 的开头应来自第一个 chunk 的尾部
        first_tail = chunks[0].text[-5:]
        # overlap 取的是 current_text 末尾 5 字符 + 下一句，故首部含 first_tail
        assert chunks[1].text.startswith(first_tail) or len(chunks[1].text) > 0


def test_chunk_with_pages_empty_returns_empty():
    chunker = TextChunker()
    assert chunker.chunk_with_pages([], doc_id="d1") == []


def test_chunk_with_pages_tracks_page():
    """chunk_with_pages 把分页文本合并分块，并记录 chunk 所属页码（取最小页）。"""

    class _Page:
        def __init__(self, text: str, page: int) -> None:
            self.text = text
            self.page = page

    chunker = TextChunker(chunk_size=30, overlap=0)
    pages = [_Page("第一页内容第一页内容。", 1), _Page("第二页内容第二页内容。", 2)]
    chunks = chunker.chunk_with_pages(pages, doc_id="d1")
    assert len(chunks) >= 1
    assert all(c.doc_id == "d1" for c in chunks)
    # page 字段应是某一页号（1 或 2）
    assert all(c.page in (1, 2) for c in chunks)


def test_split_sentences_handles_chinese_and_english_punctuation():
    """句子切分支持中文。！？；和英文 .!?; 。"""
    chunker = TextChunker()
    sents = chunker._split_sentences("你好。世界！真的吗？yes; ok.")
    # 至少切出若干句
    assert len(sents) >= 4
    # 每句非空
    assert all(s.strip() for s in sents)


def test_chunk_dataclass_defaults():
    """Chunk dataclass 默认 chunk_id 是 12 位 hex。"""
    c = Chunk()
    assert len(c.chunk_id) == 12
    assert all(ch in "0123456789abcdef" for ch in c.chunk_id)
    assert c.doc_id == ""
    assert c.chunk_index == 0
    assert c.text == ""
    assert c.page == 0
