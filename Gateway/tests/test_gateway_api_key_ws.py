from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from main import app


@pytest.fixture(autouse=True)
def _clean_gateway_guard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYES_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOWED_ORIGINS", raising=False)


def _assert_ping_pong(websocket) -> None:
    websocket.send_text("__ping__")
    for _ in range(8):
        if websocket.receive_text() == "__pong__":
            return
    raise AssertionError("expected __pong__ within first websocket messages")


def test_ws_events_connects_without_key_when_auth_disabled() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as websocket:
            _assert_ping_pong(websocket)


def test_ws_events_rejects_without_key_when_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_API_KEY", "abc")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/events") as websocket:
                websocket.receive_text()
    assert int(getattr(exc_info.value, "code", -1)) == 1008


def test_ws_events_accepts_query_api_key_when_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_API_KEY", "abc")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events?api_key=abc") as websocket:
            _assert_ping_pong(websocket)
