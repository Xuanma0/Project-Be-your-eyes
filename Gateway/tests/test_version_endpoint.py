from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(autouse=True)
def _clean_guard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYES_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("BYES_VERSION_OVERRIDE", raising=False)
    monkeypatch.delenv("BYES_GIT_SHA", raising=False)


def test_version_endpoint_returns_repo_version() -> None:
    expected = (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()
    with TestClient(app) as client:
        response = client.get("/api/version")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["version"] == expected
    assert isinstance(payload["startedTsMs"], int)
    assert isinstance(payload["uptimeSec"], (int, float))
    assert "profile" in payload


def test_version_endpoint_honors_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_VERSION_OVERRIDE", "v-local-override")
    with TestClient(app) as client:
        response = client.get("/api/version")
    assert response.status_code == 200, response.text
    assert response.json()["version"] == "v-local-override"


def test_version_requires_api_key_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_API_KEY", "abc")
    with TestClient(app) as client:
        unauthorized = client.get("/api/version")
        authorized = client.get("/api/version", headers={"X-BYES-API-Key": "abc"})
    assert unauthorized.status_code == 401, unauthorized.text
    assert authorized.status_code == 200, authorized.text
