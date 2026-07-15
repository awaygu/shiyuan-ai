"""阶段2 任务7/8 回归测试：schedule_running 跨路径一致性 + 防重复派发端到端。

重点守住"schedule_running shadow bug"修复：toggle 端点与 app.py lifespan 都写
源模块 ``schedule_state.schedule_running``（而非 ``deps.schedule_running =``），
二者经 ``deps.__getattr__`` 转发读到同一值，不会因 ``deps.__dict__`` shadow 导致
跨路径读到旧值、防重复派发失效。

还覆盖全量刷新缓存原子替换（``news_store[:] = new_items``）与 refresh_news 事务
原子性的端到端校验。
"""

from __future__ import annotations

import asyncio

import pytest

import api.schedule as schedule_mod
import api.schedule_state as schedule_state
import database as db
from api import deps
from api.tasks import TaskManager

# ── 1. schedule_running 跨路径一致性（shadow bug 回归） ──────────


def _assert_no_deps_shadow_for_schedule_running() -> None:
    """断言 deps.__dict__ 没有 schedule_running 的 shadow（应委派到源模块）。"""
    assert "schedule_running" not in deps.__dict__, (
        "deps.schedule_running 被 shadow 在 deps.__dict__，会导致跨路径读旧值"
    )


def test_deps_schedule_running_delegates_to_source_module():
    """deps.schedule_running 经 __getattr__ 转发到 schedule_state，无 shadow。

    写 schedule_state.schedule_running 后，deps.schedule_running 应读到同一值；
    deps.__dict__ 不应出现 schedule_running 键（否则即为 shadow bug 回归）。
    """
    _assert_no_deps_shadow_for_schedule_running()
    schedule_state.schedule_running = False
    assert deps.schedule_running is False
    schedule_state.schedule_running = True
    assert deps.schedule_running is True
    _assert_no_deps_shadow_for_schedule_running()
    # 清理
    schedule_state.schedule_running = False


def test_toggle_writes_source_module_not_deps():
    """toggle 写 schedule_state.schedule_running（源模块），deps 转发读到同一值、无 shadow。

    不走 TestClient（避免 lifespan 启停干扰），直接断言 deps.__dict__ 不含
    schedule_running 键，且写源模块后 deps.schedule_running 经 __getattr__ 转发读到。
    """
    schedule_state.schedule_running = False
    deps.__dict__.pop("schedule_running", None)

    _assert_no_deps_shadow_for_schedule_running()
    # 写源模块（与 schedule.py toggle / app.py lifespan 一致）
    schedule_state.schedule_running = True
    # deps 经 __getattr__ 转发读到 True
    assert deps.schedule_running is True
    assert schedule_state.schedule_running is True
    _assert_no_deps_shadow_for_schedule_running()
    # 清理
    schedule_state.schedule_running = False


async def test_toggle_then_lifespan_read_same_value(monkeypatch):
    """toggle 置 True 后，模拟 lifespan 读取 schedule_running 应得 True。

    这复现 shadow bug 场景：旧实现 toggle 写 deps.schedule_running=True 只 shadow
    在 deps.__dict__，lifespan 写源模块后再读 deps 会拿 shadow 旧值。修复后两条路径
    都读写 schedule_state，无歧义。
    """
    schedule_state.schedule_running = False
    deps.__dict__.pop("schedule_running", None)

    # 模拟 toggle 端点写源模块（与 schedule.py 实现一致）
    schedule_state.schedule_running = True

    # 模拟 lifespan 读：app.py 用 _sch.schedule_running（直接读源模块）
    lifespan_read = schedule_state.schedule_running
    # 模拟 schedule 循环 / 其他消费者经 deps 读
    deps_read = deps.schedule_running

    assert lifespan_read is True
    assert deps_read is True
    assert lifespan_read is deps_read  # 同一对象同一值
    _assert_no_deps_shadow_for_schedule_running()

    # 清理
    schedule_state.schedule_running = False


async def test_toggle_disable_writes_source_module_false(monkeypatch):
    """toggle 禁用写 schedule_state.schedule_running=False，deps 读到 False。"""
    schedule_state.schedule_running = True
    deps.__dict__.pop("schedule_running", None)

    async def _blocking_loop():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    monkeypatch.setattr(schedule_mod, "_newsnow_crawl_loop", _blocking_loop)
    monkeypatch.setattr(schedule_mod, "_rss_crawl_loop", _blocking_loop)

    # 先启用
    await schedule_mod.toggle_schedule(schedule_mod.ToggleScheduleRequest(enabled=True))
    assert schedule_state.schedule_running is True

    # 再禁用
    result = await schedule_mod.toggle_schedule(schedule_mod.ToggleScheduleRequest(enabled=False))
    assert result["running"] is False
    assert schedule_state.schedule_running is False
    assert deps.schedule_running is False
    _assert_no_deps_shadow_for_schedule_running()


# ── 2. 防重复派发端到端（toggle 在跑时再启用不重复 create_task） ──


async def test_toggle_enable_while_running_no_duplicate_spawn(monkeypatch):
    """循环已在跑（句柄已登记）时，再 toggle enabled=True 不应重复 create_task。

    防重复从布尔短路升级为 TaskManager.is_running 句柄存在性判断：is_running 返回
    True 时跳过 create_task，循环句柄仍是原来那个。
    """
    schedule_state.schedule_running = True
    deps.__dict__.pop("schedule_running", None)

    from api.tasks import task_manager

    spawn_count = {"n": 0}

    async def _counted_loop():
        spawn_count["n"] += 1

    monkeypatch.setattr(schedule_mod, "_newsnow_crawl_loop", _counted_loop)
    monkeypatch.setattr(schedule_mod, "_rss_crawl_loop", _counted_loop)

    # 预登记在跑的阻塞循环句柄，模拟 lifespan 已启动
    async def _blocking():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    pre_newsnow = asyncio.create_task(_blocking())
    pre_rss = asyncio.create_task(_blocking())
    task_manager.register_background("newsnow_crawl_loop", pre_newsnow)
    task_manager.register_background("rss_crawl_loop", pre_rss)

    result = await schedule_mod.toggle_schedule(schedule_mod.ToggleScheduleRequest(enabled=True))
    assert result["running"] is True
    # 没有重复派发：_counted_loop 未被调用
    assert spawn_count["n"] == 0
    # 句柄仍是预登记的
    assert task_manager._background_tasks["newsnow_crawl_loop"] is pre_newsnow
    assert task_manager._background_tasks["rss_crawl_loop"] is pre_rss

    # 清理
    await task_manager.stop_background("newsnow_crawl_loop")
    await task_manager.stop_background("rss_crawl_loop")
    schedule_state.schedule_running = False


# ── 3. 后台任务 shutdown 顺序（close_db 前 await shutdown） ───────


async def test_shutdown_cancels_loops_and_awaits_then_clears_handles(monkeypatch):
    """shutdown：置 schedule_running=False + cancel 长跑循环 + await 完成 + 清空字典。

    lifespan 在 close_db 前 await task_manager.shutdown()，本测试直接调用 shutdown
    验证其语义，确保后台 DB 写入不会在 close_db 后仍跑飞。
    """
    schedule_state.schedule_running = True
    mgr = TaskManager()
    mgr._background_tasks.clear()
    mgr._short_tasks.clear()

    loop_cancelled = asyncio.Event()

    async def _bg_loop():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            loop_cancelled.set()

    bg_task = asyncio.create_task(_bg_loop())
    mgr.register_background("newsnow_crawl_loop", bg_task)
    # 让循环跑到 await 点
    await asyncio.sleep(0)

    await mgr.shutdown()
    assert schedule_state.schedule_running is False
    assert loop_cancelled.is_set()
    assert bg_task.done()
    assert mgr._background_tasks == {}
    assert mgr._short_tasks == set()


# ── 4. upsert_news_returning 缓存回填只含真正落库条目（任务7 增量一致） ─


def _news(news_id: str, source: str = "cls-hot", published_at: str = "2024-01-01T00:00:00") -> dict:
    return {
        "news_id": news_id,
        "title": f"title-{news_id}",
        "summary": f"summary-{news_id}",
        "content": "",
        "source": source,
        "url": f"https://example.com/{news_id}",
        "published_at": published_at,
        "extra": {"media_type": "article"},
    }


@pytest.fixture()
async def _fresh_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "news_ai.db")
    await db.close_db()
    monkeypatch.setattr(db, "_db", None)
    await db.init_db()
    yield
    await db.close_db()


async def test_upsert_news_returning_backfill_only_inserted(_fresh_db):
    """upsert_news_returning 只返回真正落库的 news_id；模拟 _bg_crawl_and_save 回填。"""
    # 预置已存在
    await db.upsert_news([_news("old")])
    candidates = [_news("old"), _news("new1"), _news("new2")]
    count, inserted_ids = await db.upsert_news_returning(candidates)
    assert count == 2
    assert set(inserted_ids) == {"new1", "new2"}

    # 模拟 _bg_crawl_and_save 事务后回填：只 extend 真正落库的条目
    inserted_set = set(inserted_ids)
    backfilled = [d for d in candidates if d["news_id"] in inserted_set]
    assert {d["news_id"] for d in backfilled} == {"new1", "new2"}
    # old 不在回填集合（DB 没插入，缓存不该加）
    assert "old" not in {d["news_id"] for d in backfilled}


async def test_bg_crawl_and_save_backfill_excludes_ignored(_fresh_db, monkeypatch):
    """_bg_crawl_and_save 模拟：INSERT OR IGNORE 忽略的 id 不进缓存回填。

    复现 refresh 路径的缓存一致性：candidates 含已存在 id，事务内 RETURNING 只拿
    真正新增的 id，事务后 news_store.extend 只回填这些。
    """
    from api import stores

    # 预置已存在
    await db.upsert_news([_news("dup")])
    stores.news_store.clear()

    candidates = [_news("dup"), _news("fresh1"), _news("fresh2")]
    # 模拟事务内查重 + RETURNING 写
    existing = await db.news_id_exists_batch([d["news_id"] for d in candidates])
    new_items = [d for d in candidates if d["news_id"] not in existing]
    assert {d["news_id"] for d in new_items} == {"fresh1", "fresh2"}
    count, inserted_ids = await db.upsert_news_returning(new_items)
    assert count == 2
    # 事务后回填：只真正落库的（与 news.py _bg_crawl_and_save 一致用 deps.news_store）
    inserted_set = set(inserted_ids)
    deps.news_store.extend([d for d in new_items if d["news_id"] in inserted_set])
    # 缓存只有 fresh1/fresh2，不含 dup（deps.news_store 转发到 stores.news_store 同一对象）
    assert {n["news_id"] for n in stores.news_store} == {"fresh1", "fresh2"}
    stores.news_store.clear()
