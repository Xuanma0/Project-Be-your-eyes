from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(autouse=True)
def _clean_gateway_guard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYES_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_ORIGINS", raising=False)


def test_api_models_open_when_gateway_key_unset() -> None:
    with TestClient(app) as client:
        response = client.get("/api/models")
    assert response.status_code == 200, response.text


def test_api_models_unauthorized_without_key_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_API_KEY", "abc")
    with TestClient(app) as client:
        response = client.get("/api/models")
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "Unauthorized"}


def test_api_models_authorized_with_key_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_API_KEY", "abc")
    with TestClient(app) as client:
        response = client.get("/api/models", headers={"X-BYES-API-Key": "abc"})
    assert response.status_code == 200, response.text
