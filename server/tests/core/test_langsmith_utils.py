"""``core.langsmith_utils.traceable`` 适配层测试。

tracing 关闭时装饰器必须透传原函数、零副作用；开启时透传给
``langsmith.traceable`` 并保留 name/tags/metadata。所有用例显式 monkeypatch
``LANGSMITH_TRACING`` 与 ``_traceable``，不依赖运行环境的 .env 设置。
"""

from __future__ import annotations


def _set_tracing_off(monkeypatch):
    import core.langsmith_utils as ls_utils

    monkeypatch.setattr(ls_utils, "LANGSMITH_TRACING", False)
    monkeypatch.setattr(ls_utils, "_traceable", None)
    return ls_utils


def _set_tracing_on(monkeypatch, fake_traceable):
    import core.langsmith_utils as ls_utils

    monkeypatch.setattr(ls_utils, "LANGSMITH_TRACING", True)
    monkeypatch.setattr(ls_utils, "_traceable", fake_traceable)
    return ls_utils


def test_passthrough_when_tracing_off(monkeypatch):
    """LANGSMITH_TRACING=false 时装饰器透传，调用结果与副作用不变。"""
    ls_utils = _set_tracing_off(monkeypatch)

    calls: list[int] = []

    @ls_utils.traceable("kb: doc_summary", tags=["kb_upload"], metadata={"model": "m"})
    def summarize(text: str) -> str:
        calls.append(len(text))
        return text.upper()

    # 装饰后仍是原函数行为
    assert summarize("hello") == "HELLO"
    assert calls == [5]
    # 再次调用确认无隐藏状态
    assert summarize("hi") == "HI"
    assert calls == [5, 2]


def test_passthrough_preserves_sync_and_async(monkeypatch):
    """透传路径对同步与异步函数都生效。"""
    ls_utils = _set_tracing_off(monkeypatch)

    @ls_utils.traceable("sync", metadata={"k": "v"})
    def sync_fn(x: int) -> int:
        return x * 2

    @ls_utils.traceable("async", metadata={"k": "v"})
    async def async_fn(x: int) -> int:
        return x * 3

    assert sync_fn(21) == 42
    import asyncio

    assert asyncio.run(async_fn(14)) == 42


def test_delegates_to_langsmith_when_tracing_on(monkeypatch):
    """LANGSMITH_TRACING=true 时透传 name/tags/metadata 给 langsmith.traceable。"""
    captured: dict = {}

    def fake_traceable(name, *, tags=None, metadata=None):
        captured["name"] = name
        captured["tags"] = tags
        captured["metadata"] = metadata

        def _decorator(fn):
            def _wrapped(*args, **kwargs):
                return fn(*args, **kwargs)

            return _wrapped

        return _decorator

    ls_utils = _set_tracing_on(monkeypatch, fake_traceable)

    @ls_utils.traceable("embed: dashscope", tags=["embedding"], metadata={"model": "v4"})
    def embed(texts):
        return texts

    assert embed(["a"]) == ["a"]
    assert captured["name"] == "embed: dashscope"
    assert captured["tags"] == ["embedding"]
    assert captured["metadata"] == {"model": "v4"}


def test_default_empty_tags_and_metadata(monkeypatch):
    """tags/metadata 缺省时透传空列表/空字典，不传 None 给 langsmith。"""
    captured: dict = {}

    def fake_traceable(name, *, tags=None, metadata=None):
        captured["tags"] = tags
        captured["metadata"] = metadata

        def _decorator(fn):
            return fn

        return _decorator

    ls_utils = _set_tracing_on(monkeypatch, fake_traceable)

    @ls_utils.traceable("only_name")
    def fn():
        return 1

    fn()
    assert captured["tags"] == []
    assert captured["metadata"] == {}


def test_traceable_off_returns_callable_decorator(monkeypatch):
    """关闭时 traceable(...) 必须返回一个可调用装饰器，且不报错。"""
    ls_utils = _set_tracing_off(monkeypatch)
    decorator = ls_utils.traceable("any name", tags=["t"], metadata={"k": "v"})
    assert callable(decorator)

    @decorator
    def fn(x):
        return x + 1

    assert fn(1) == 2
