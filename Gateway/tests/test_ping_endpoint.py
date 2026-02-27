from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(autouse=True)
def _clean_guard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYES_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("BYES_EMIT_NET_DEBUG", raising=False)


def test_ping_echoes_client_fields_and_server_timestamps() -> None:
    body = {"deviceId": "quest-a", "seq": 7, "clientSendTsMs": 12345}
    with TestClient(app) as client:
        response = client.post("/api/ping", json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deviceId"] == "quest-a"
    assert payload["seq"] == 7
    assert payload["clientSendTsMs"] == 12345
    assert isinstance(payload["serverRecvTsMs"], int)
    assert isinstance(payload["serverSendTsMs"], int)
    assert payload["serverSendTsMs"] >= payload["serverRecvTsMs"]


def test_ping_defaults_device_id_when_missing() -> None:
    with TestClient(app) as client:
        response = client.post("/api/ping", json={"seq": 1, "clientSendTsMs": 10})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deviceId"] == "default"
    assert payload["seq"] == 1
    assert payload["clientSendTsMs"] == 10


def test_ping_requires_api_key_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_API_KEY", "abc")
    body = {"deviceId": "quest-a", "seq": 8, "clientSendTsMs": 123}
    with TestClient(app) as client:
        unauthorized = client.post("/api/ping", json=body)
        authorized = client.post("/api/ping", json=body, headers={"X-BYES-API-Key": "abc"})
    assert unauthorized.status_code == 401, unauthorized.text
    assert authorized.status_code == 200, authorized.text

