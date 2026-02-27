from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from byes.mode_state import ModeStateStore
from main import app, gateway


@pytest.fixture(autouse=True)
def _reset_mode_state_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYES_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_ORIGINS", raising=False)
    gateway.mode_state = ModeStateStore(default_mode="walk")


def test_get_mode_defaults_when_no_state() -> None:
    with TestClient(app) as client:
        response = client.get("/api/mode")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deviceId"] == "default"
    assert payload["mode"] == "walk"
    assert payload["source"] == "default"
    assert isinstance(payload["updatedTsMs"], int)
    assert payload["expiresInMs"] is None


def test_get_mode_reflects_posted_mode_for_device() -> None:
    with TestClient(app) as client:
        post = client.post(
            "/api/mode",
            json={
                "runId": "run-1",
                "frameSeq": 1,
                "mode": "read_text",
                "source": "system",
                "deviceId": "quest-a",
            },
        )
        assert post.status_code == 200, post.text
        response = client.get("/api/mode", params={"deviceId": "quest-a"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deviceId"] == "quest-a"
    assert payload["mode"] == "read_text"
    assert payload["source"] == "explicit"
    assert isinstance(payload["updatedTsMs"], int)


def test_get_mode_is_isolated_by_device_id() -> None:
    with TestClient(app) as client:
        post_a = client.post(
            "/api/mode",
            json={
                "runId": "run-a",
                "frameSeq": 1,
                "mode": "inspect",
                "source": "system",
                "deviceId": "quest-a",
            },
        )
        post_b = client.post(
            "/api/mode",
            json={
                "runId": "run-b",
                "frameSeq": 1,
                "mode": "walk",
                "source": "system",
                "deviceId": "quest-b",
            },
        )
        assert post_a.status_code == 200, post_a.text
        assert post_b.status_code == 200, post_b.text
        response_a = client.get("/api/mode", params={"deviceId": "quest-a"})
        response_b = client.get("/api/mode", params={"deviceId": "quest-b"})
    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text
    assert response_a.json()["mode"] == "inspect"
    assert response_b.json()["mode"] == "walk"


def test_get_mode_requires_api_key_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_API_KEY", "abc")
    with TestClient(app) as client:
        unauthorized = client.get("/api/mode")
        authorized = client.get("/api/mode", headers={"X-BYES-API-Key": "abc"})
    assert unauthorized.status_code == 401, unauthorized.text
    assert authorized.status_code == 200, authorized.text
