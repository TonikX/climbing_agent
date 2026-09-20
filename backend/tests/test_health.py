import os

os.environ.setdefault("INTERNAL_API_KEY", "test-key")
os.environ.setdefault("DB_PASSWORD", "test-password")

from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
