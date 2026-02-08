from __future__ import annotations

import io
import json
import re
import time
from typing import Any

from fastapi.testclient import TestClient

from main import app, gateway

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="([^"]*)"')
SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


class _CaptureConnection:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def broadcast_json(self, obj: dict[str, Any]) -> None:
        self.messages.append(obj)


def _parse_metrics(text: str) -> dict[SeriesKey, float]:
    rows: dict[SeriesKey, float] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        labels_raw = match.group(2)
        value_raw = match.group(3)
        try:
            value = float(value_raw)
        except ValueError:
            continue
        labels: tuple[tuple[str, str], ...] = tuple()
        if labels_raw:
            labels = tuple(sorted(_LABEL_RE.findall(labels_raw), key=lambda item: item[0]))
        rows[(name, labels)] = value
    return rows


def _metric_total(samples: dict[SeriesKey, float], metric_name: str) -> float:
    return sum(value for (name, _labels), value in samples.items() if name == metric_name)


def _metric_with_labels(samples: dict[SeriesKey, float], metric_name: str, labels: dict[str, str]) -> float:
    labels_key = tuple(sorted(labels.items(), key=lambda item: item[0]))
    return samples.get((metric_name, labels_key), 0.0)


def _speedup_mock_tools() -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = 0
    ocr = gateway.registry.get("mock_ocr")
    if ocr is not None and hasattr(ocr, "_delay_ms"):
        ocr._delay_ms = 0


def _send_frames(client: TestClient, count: int) -> None:
    meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
    for _ in range(count):
        files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
        response = client.post("/api/frame", files=files, data={"meta": meta})
        assert response.status_code == 200


def _wait_for_pending_confirm(client: TestClient, timeout_sec: float = 10.0) -> dict[str, Any] | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        response = client.get("/api/confirm/pending")
        assert response.status_code == 200
        payload = response.json()
        pending = payload.get("pending")
        if isinstance(pending, dict) and pending.get("confirmId"):
            return pending
        time.sleep(0.1)
    return None


def test_confirm_request_emitted_on_crosscheck_kind() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")
        before = _parse_metrics(client.get("/metrics").text)

        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            response = client.post("/api/dev/crosscheck", json={"kind": "vision_without_depth", "durationMs": 6000})
            assert response.status_code == 200
            _send_frames(client, 8)
            pending = _wait_for_pending_confirm(client)
            assert pending is not None
        finally:
            gateway.connections = original_connections  # type: ignore[assignment]

        confirm_events = [
            item
            for item in capture.messages
            if isinstance(item, dict)
            and str(item.get("type", "")) == "action_plan"
            and bool(item.get("confirmId"))
        ]
        assert confirm_events, "expected at least one confirm action_plan event"
        first = confirm_events[0]
        assert str(first.get("confirmKind", "")) == "transparent_obstacle"
        assert isinstance(first.get("confirmOptions"), list)

        after = _parse_metrics(client.get("/metrics").text)
        delta = _metric_with_labels(
            after,
            "byes_confirm_request_total",
            {"kind": "transparent_obstacle"},
        ) - _metric_with_labels(
            before,
            "byes_confirm_request_total",
            {"kind": "transparent_obstacle"},
        )
        assert delta >= 1


def test_confirm_response_writes_world_state_and_suppresses_reask() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")
        before = _parse_metrics(client.get("/metrics").text)

        response = client.post("/api/dev/crosscheck", json={"kind": "vision_without_depth", "durationMs": 6000})
        assert response.status_code == 200
        _send_frames(client, 8)
        pending = _wait_for_pending_confirm(client)
        assert pending is not None

        submit = client.post(
            "/api/confirm",
            json={"confirmId": pending["confirmId"], "answer": "no", "source": "pytest"},
        )
        assert submit.status_code == 200
        assert submit.json().get("ok") is True
        assert submit.json().get("resolved") is True

        snapshot = gateway.world_state.snapshot(session_id="default", now_ms=int(time.time() * 1000))
        assert "transparent_obstacle" in set(snapshot.confirm_suppressed_kinds)

        second = client.post("/api/dev/crosscheck", json={"kind": "vision_without_depth", "durationMs": 6000})
        assert second.status_code == 200
        _send_frames(client, 8)
        after = _parse_metrics(client.get("/metrics").text)

        response_delta = _metric_with_labels(
            after,
            "byes_confirm_response_total",
            {"kind": "transparent_obstacle", "answer": "no"},
        ) - _metric_with_labels(
            before,
            "byes_confirm_response_total",
            {"kind": "transparent_obstacle", "answer": "no"},
        )
        request_delta = _metric_with_labels(
            after,
            "byes_confirm_request_total",
            {"kind": "transparent_obstacle"},
        ) - _metric_with_labels(
            before,
            "byes_confirm_request_total",
            {"kind": "transparent_obstacle"},
        )
        assert response_delta >= 1
        # First run creates one request, second run should be suppressed (no second request).
        assert int(round(request_delta)) == 1


def test_safemode_blocks_confirm_request_and_counts_suppressed() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")
        before = _parse_metrics(client.get("/metrics").text)

        fault = client.post("/api/fault/set", json={"tool": "mock_risk", "mode": "timeout", "value": True})
        assert fault.status_code == 200
        try:
            response = client.post("/api/dev/crosscheck", json={"kind": "vision_without_depth", "durationMs": 6000})
            assert response.status_code == 200
            _send_frames(client, 30)
            time.sleep(0.5)
            after = _parse_metrics(client.get("/metrics").text)
        finally:
            client.post("/api/fault/clear")

        request_delta = _metric_with_labels(
            after,
            "byes_confirm_request_total",
            {"kind": "transparent_obstacle"},
        ) - _metric_with_labels(
            before,
            "byes_confirm_request_total",
            {"kind": "transparent_obstacle"},
        )
        suppressed_delta = _metric_with_labels(
            after,
            "byes_confirm_suppressed_total",
            {"reason": "safe_mode"},
        ) - _metric_with_labels(
            before,
            "byes_confirm_suppressed_total",
            {"reason": "safe_mode"},
        )
        safemode_delta = _metric_total(after, "byes_safemode_enter_total") - _metric_total(
            before,
            "byes_safemode_enter_total",
        )
        assert int(round(safemode_delta)) >= 1
        assert int(round(request_delta)) == 0
        assert suppressed_delta >= 1
