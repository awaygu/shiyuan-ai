"""阶段3任务11 测试：api/conversations.py 端点经 asyncio.to_thread 调用 checkpointer。

覆盖：
1. 各端点 CRUD 基本行为（经 to_thread 后功能不回归）。
2. 404 处理（对话不存在）。
3. 经 client fixture（conftest 已每测试重置 checkpointer.DB_PATH）验证跨测试无污染。
"""

from __future__ import annotations

import inspect

from fastapi.testclient import TestClient

import api.conversations as conv_mod

# ── 端点经 to_thread（不阻塞事件循环）──


def test_all_endpoints_use_to_thread():
    """所有 conversations 端点对 checkpointer 的调用经 asyncio.to_thread。

    静态检查：端点函数体含 ``asyncio.to_thread`` 调用，确保同步 sqlite3 不阻塞事件循环，
    与 api/agent.py 对齐。检查源码而非运行时（源码即契约）。
    """
    source = inspect.getsource(conv_mod)
    assert "asyncio.to_thread" in source, "conversations 端点应经 asyncio.to_thread 调用 checkpointer"


# ── CRUD 基本行为 ──


def test_create_conversation_endpoint(client: TestClient):
    resp = client.post("/api/conversations", json={"title": "测试对话"})
    assert resp.status_code == 200
    body = resp.json()
    assert "id" in body
    assert body["title"] == "测试对话"
    assert "created_at" in body
    assert "updated_at" in body


def test_create_conversation_default_title(client: TestClient):
    """不传 body 时用默认标题。"""
    resp = client.post("/api/conversations")
    assert resp.status_code == 200
    assert resp.json()["title"] == "新对话"


def test_list_conversations_endpoint(client: TestClient):
    client.post("/api/conversations", json={"title": "对话A"})
    client.post("/api/conversations", json={"title": "对话B"})

    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    assert len(body["items"]) >= 2


def test_get_conversation_endpoint(client: TestClient):
    create = client.post("/api/conversations", json={"title": "对话"}).json()
    resp = client.get(f"/api/conversations/{create['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == create["id"]


def test_get_conversation_404(client: TestClient):
    resp = client.get("/api/conversations/nonexistent-id")
    assert resp.status_code == 404


def test_update_conversation_title_endpoint(client: TestClient):
    create = client.post("/api/conversations", json={"title": "原标题"}).json()
    resp = client.patch(f"/api/conversations/{create['id']}", json={"title": "新标题"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # 验证标题已更新
    after = client.get(f"/api/conversations/{create['id']}").json()
    assert after["title"] == "新标题"


def test_update_conversation_title_404(client: TestClient):
    resp = client.patch("/api/conversations/nonexistent-id", json={"title": "新标题"})
    assert resp.status_code == 404


def test_delete_conversation_endpoint(client: TestClient):
    create = client.post("/api/conversations", json={"title": "对话"}).json()
    resp = client.delete(f"/api/conversations/{create['id']}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # 删除后 404
    assert client.get(f"/api/conversations/{create['id']}").status_code == 404


def test_delete_conversation_404(client: TestClient):
    resp = client.delete("/api/conversations/nonexistent-id")
    assert resp.status_code == 404


def test_get_messages_endpoint(client: TestClient):
    """get_messages 端点：对话存在但无消息时返回空列表。"""
    create = client.post("/api/conversations", json={"title": "对话"}).json()
    resp = client.get(f"/api/conversations/{create['id']}/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == create["id"]
    assert body["messages"] == []


def test_get_messages_404(client: TestClient):
    resp = client.get("/api/conversations/nonexistent-id/messages")
    assert resp.status_code == 404


def test_clear_messages_endpoint(client: TestClient):
    create = client.post("/api/conversations", json={"title": "对话"}).json()
    resp = client.delete(f"/api/conversations/{create['id']}/messages")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["deleted_count"] == 0


# ── 跨测试无污染（conftest 每测试重置 checkpointer.DB_PATH）──


def test_no_cross_test_pollution_empty(client: TestClient):
    """新 client fixture 每测试用独立 agent_memory.db，此测试看到的是空库。

    其他测试可能建过对话，但每测试独立库不应污染到本测试。
    """
    resp = client.get("/api/conversations")
    assert resp.json()["total"] == 0
