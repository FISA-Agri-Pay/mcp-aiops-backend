from fastapi.testclient import TestClient

from aiops_platform.core.config import settings
from aiops_platform.main import create_app


def test_health_check() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_cors_allows_configured_frontend_origin(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cors_allow_origins", "https://kongkongpatpat.shop")
    client = TestClient(create_app())

    response = client.options(
        "/health",
        headers={
            "Origin": "https://kongkongpatpat.shop",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://kongkongpatpat.shop"
