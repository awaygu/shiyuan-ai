"""DocumentLoader 解析测试：_clean_text、TXT/MD 加载、不支持类型、PageText/Document dataclass。

PDF/DOCX/Image 加载需 pdfplumber/docx/PIL/LLM，留作集成测试，不在此覆盖。
重点测离线可复现的 _clean_text 与 _load_text 路径。
"""

from __future__ import annotations

import pytest

from rag.loader import DocumentLoader, PageText, _clean_text


def test_clean_text_strips_garbled_and_normalizes_whitespace():
    """_clean_text 去除 cid 占位符、控制字符、零宽字符、替换字符，合并空白。"""
    raw = "cid(123)你好\x00世界\n\n\n\n这是测试​文本�"
    cleaned = _clean_text(raw)
    assert "cid(123)" not in cleaned
    assert "\x00" not in cleaned
    assert "�" not in cleaned
    # 连续空行合并为最多两个
    assert "\n\n\n" not in cleaned


def test_clean_text_empty_returns_empty():
    assert _clean_text("") == ""
    assert _clean_text(None) == ""


def test_clean_text_collapses_spaces_and_tabs():
    assert _clean_text("a    b\t\tc") == "a b c"


def test_loader_unsupported_type_raises(tmp_path):
    """不支持的扩展名抛 ValueError。"""
    f = tmp_path / "data.xyz"
    f.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file type"):
        DocumentLoader().load(f)


def test_loader_load_txt_utf8(tmp_path):
    """TXT 文件按 utf-8 加载，返回 Document 含 pages 与 cleaned text。"""
    f = tmp_path / "doc.txt"
    f.write_text("第一行内容。\n第二行内容。\n第三行内容。", encoding="utf-8")
    doc = DocumentLoader().load(f, doc_id="d1")
    assert doc.doc_id == "d1"
    assert doc.file_type == ".txt"
    assert doc.filename == "doc.txt"
    assert doc.file_size > 0
    assert "第一行内容" in doc.text
    assert len(doc.pages) >= 1
    assert all(isinstance(p, PageText) for p in doc.pages)


def test_loader_load_txt_gbk_fallback(tmp_path):
    """utf-8 解码失败时回退 gbk。"""
    f = tmp_path / "doc.txt"
    # gbk 编码的中文字符串
    f.write_bytes("中文内容测试".encode("gbk"))
    doc = DocumentLoader().load(f, doc_id="d1")
    assert "中文内容测试" in doc.text


def test_loader_load_md(tmp_path):
    """MD 文件按文本加载。"""
    f = tmp_path / "doc.md"
    f.write_text("# 标题\n\n正文内容。", encoding="utf-8")
    doc = DocumentLoader().load(f, doc_id="d1")
    assert doc.file_type == ".md"
    assert "正文内容" in doc.text


def test_loader_txt_multiple_pages(tmp_path):
    """超过 50 行的 TXT 会分成多页。"""
    lines = [f"第{i}行内容。" for i in range(120)]
    f = tmp_path / "long.txt"
    f.write_text("\n".join(lines), encoding="utf-8")
    doc = DocumentLoader().load(f)
    assert len(doc.pages) >= 2
    # 页码从 1 递增
    assert doc.pages[0].page == 1
    assert doc.pages[-1].page > 1


def test_pagetext_dataclass():
    p = PageText(page=3, text="hello")
    assert p.page == 3
    assert p.text == "hello"


def test_document_dataclass_defaults():
    from rag.loader import Document

    d = Document()
    assert d.doc_id == ""
    assert d.filename == ""
    assert d.pages == []
    assert d.metadata == {}
    assert d.file_type == ""
