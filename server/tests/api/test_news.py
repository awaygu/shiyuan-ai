"""Tests for news-related API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_news_empty(client: TestClient) -> None:
    """GET /api/news should return an empty list on a fresh database."""
    response = client.get("/api/news")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["offset"] == 0
    assert data["limit"] == 20


def test_get_news_by_source_empty(client: TestClient) -> None:
    """GET /api/news?source=... should return an empty list for unknown sources."""
    response = client.get("/api/news?source=cls-hot")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_refresh_news_mocked(client: TestClient) -> None:
    """POST /api/news/refresh should work without real crawlers."""
    response = client.post("/api/news/refresh")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["new"] == 0
    assert data["total_raw"] == 0
    assert "results" in data
