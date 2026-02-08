from __future__ import annotations

import io
import json
import re
import time
from typing import Any

from fastapi.testclient import TestClient

from main import app, gateway

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
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
        raw_labels = match.group(2)
        value_raw = match.group(3)
        try:
            value = float(value_raw)
        except ValueError:
            continue
        labels: tuple[tuple[str, str], ...] = tuple()
        if raw_labels:
            labels = tuple(sorted(_LABEL_RE.findall(raw_labels), key=lambda item: item[0]))
        rows[(name, labels)] = value
    return rows


def _metric_total(samples: dict[SeriesKey, float], name: str) -> float:
    return sum(value for (metric_name, _labels), value in samples.items() if metric_name == name)


def _wait_completed(client: TestClient, before: dict[SeriesKey, float], expected_delta: int) -> dict[SeriesKey, float]:
    deadline = time.time() + 20.0
    while time.time() < deadline:
        current = _parse_metrics(client.get("/metrics").text)
        completed = _metric_total(current, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        if completed >= expected_delta:
            return current
        time.sleep(0.1)
    return _parse_metrics(client.get("/metrics").text)


def _speedup_mock_tools() -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = 0
    ocr = gateway.registry.get("mock_ocr")
    if ocr is not None and hasattr(ocr, "_delay_ms"):
        ocr._delay_ms = 0


def _fallback_health_status(event: dict[str, Any]) -> str:
    summary = str(event.get("summary", "")).lower()
    if "safe_mode" in summary:
        return "SAFE_MODE"
    if "degraded" in summary:
        return "DEGRADED"
    if "normal" in summary:
        return "NORMAL"
    if "waiting_client" in summary:
        return "WAITING_CLIENT"
    return "HEALTH_OTHER"


def test_health_contract_stable() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        client.post("/api/dev/reset")
        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            before = _parse_metrics(client.get("/metrics").text)
            for _ in range(12):
                files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
                meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
                resp = client.post("/api/frame", files=files, data={"meta": meta})
                assert resp.status_code == 200
            _ = _wait_completed(client, before, expected_delta=12)
        finally:
            gateway.connections = original_connections  # type: ignore[assignment]

        health_events = [item for item in capture.messages if isinstance(item, dict) and item.get("type") == "health"]
        assert len(health_events) >= 1

        allowed = {"NORMAL", "DEGRADED", "SAFE_MODE", "WAITING_CLIENT"}
        health_other = 0
        for evt in health_events:
            hs = evt.get("healthStatus")
            if isinstance(hs, str) and hs in allowed:
                continue
            inferred = _fallback_health_status(evt)
            if inferred not in allowed:
                health_other += 1

        assert health_other <= 1
