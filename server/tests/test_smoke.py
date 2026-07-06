"""Smoke tests: make sure the FastAPI app starts and shuts down cleanly."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_app_startup(client: TestClient) -> None:
    """App lifespan should complete without exceptions."""
    assert client.app is not None
