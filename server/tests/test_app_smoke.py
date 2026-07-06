from fastapi.testclient import TestClient

from app import app


def test_app_docs_reachable() -> None:
    with TestClient(app) as client:
        response = client.get("/docs")
        assert response.status_code == 200
