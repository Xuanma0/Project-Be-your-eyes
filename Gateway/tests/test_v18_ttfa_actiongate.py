from __future__ import annotations

import io
import json
import re
import time
from typing import Any

from fastapi.testclient import TestClient

from byes.action_gate import ActionPlanGate
from byes.metrics import GatewayMetrics
from byes.schema import CoordFrame, EventEnvelope, EventType
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


def _metric_with_labels(samples: dict[SeriesKey, float], name: str, labels: dict[str, str]) -> float:
    labels_key = tuple(sorted(labels.items(), key=lambda item: item[0]))
    return samples.get((name, labels_key), 0.0)


def _send_frames(client: TestClient, count: int) -> None:
    for _ in range(count):
        files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
        meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
        response = client.post("/api/frame", files=files, data={"meta": meta})
        assert response.status_code == 200


def _wait_completed(client: TestClient, before: dict[SeriesKey, float], expected_delta: int, timeout_sec: float = 20.0) -> dict[SeriesKey, float]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        current = _parse_metrics(client.get("/metrics").text)
        completed = _metric_total(current, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        if completed >= expected_delta:
            return current
        time.sleep(0.1)
    return _parse_metrics(client.get("/metrics").text)


def _speedup_mock_tools(risk_delay_ms: int = 0, ocr_delay_ms: int = 0) -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = risk_delay_ms
    ocr = gateway.registry.get("mock_ocr")
    if ocr is not None and hasattr(ocr, "_delay_ms"):
        ocr._delay_ms = ocr_delay_ms


def _first_safe_mode_ms(messages: list[dict[str, Any]]) -> int | None:
    for message in messages:
        if str(message.get("type", "")) != "health":
            continue
        status = str(message.get("healthStatus", "")).upper()
        summary = str(message.get("summary", "")).lower()
        if status == "SAFE_MODE" or "safe_mode" in summary:
            ts = message.get("timestampMs")
            if isinstance(ts, int):
                return ts
    return None


def test_ttfa_observed_once_per_frame() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools(risk_delay_ms=0, ocr_delay_ms=0)
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")
        before = _parse_metrics(client.get("/metrics").text)

        _send_frames(client, 50)
        after = _wait_completed(client, before, expected_delta=50)

        frame_received_delta = _metric_total(after, "byes_frame_received_total") - _metric_total(
            before, "byes_frame_received_total"
        )
        frame_completed_delta = _metric_total(after, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        e2e_count_delta = _metric_total(after, "byes_e2e_latency_ms_count") - _metric_total(
            before, "byes_e2e_latency_ms_count"
        )
        ttfa_hist_delta = _metric_total(after, "byes_ttfa_ms_count") - _metric_total(
            before, "byes_ttfa_ms_count"
        )
        ttfa_count_delta = _metric_total(after, "byes_ttfa_count_total") - _metric_total(
            before, "byes_ttfa_count_total"
        )

        assert int(round(frame_received_delta)) == 50
        assert int(round(frame_completed_delta)) == 50
        assert int(round(e2e_count_delta)) == 50
        assert ttfa_hist_delta > 0
        assert ttfa_hist_delta <= frame_completed_delta
        assert int(round(ttfa_count_delta)) == 50


def test_stage1_emits_before_stage2() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools(risk_delay_ms=0, ocr_delay_ms=280)
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")

        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            _send_frames(client, 1)
            deadline = time.time() + 8.0
            while time.time() < deadline:
                has_action = any(
                    str(item.get("type", "")) in {"risk", "action_plan"}
                    for item in capture.messages
                    if isinstance(item, dict)
                )
                has_perception = any(
                    str(item.get("type", "")) == "perception"
                    for item in capture.messages
                    if isinstance(item, dict)
                )
                if has_action and has_perception:
                    break
                time.sleep(0.1)
        finally:
            gateway.connections = original_connections  # type: ignore[assignment]

        non_health = [
            item for item in capture.messages if isinstance(item, dict) and str(item.get("type", "")) != "health"
        ]
        first_action = next((item for item in non_health if str(item.get("type", "")) in {"risk", "action_plan"}), None)
        first_perception = next((item for item in non_health if str(item.get("type", "")) == "perception"), None)

        assert first_action is not None
        assert first_perception is not None
        assert int(first_action.get("timestampMs", 0)) <= int(first_perception.get("timestampMs", 0))
        assert str(first_action.get("stage", "")) == "stage1"
        assert str(first_perception.get("stage", "")) == "stage2"


def test_actiongate_blocks_in_safe_mode() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools(risk_delay_ms=0, ocr_delay_ms=0)
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")

        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            before = _parse_metrics(client.get("/metrics").text)
            set_fault = client.post("/api/fault/set", json={"tool": "mock_risk", "mode": "timeout", "value": True})
            assert set_fault.status_code == 200
            _send_frames(client, 50)
            after = _wait_completed(client, before, expected_delta=50)
        finally:
            client.post("/api/fault/clear")
            gateway.connections = original_connections  # type: ignore[assignment]

        block_delta = _metric_total(after, "byes_actiongate_block_total") - _metric_total(
            before, "byes_actiongate_block_total"
        )
        assert block_delta > 0

        first_safe_mode_ms = _first_safe_mode_ms(capture.messages)
        assert first_safe_mode_ms is not None

        for message in capture.messages:
            if not isinstance(message, dict):
                continue
            ts = message.get("timestampMs")
            if not isinstance(ts, int) or ts < int(first_safe_mode_ms):
                continue
            event_type = str(message.get("type", ""))
            assert event_type != "perception"
            assert event_type != "action_plan"


def test_actiongate_patches_in_degraded() -> None:
    metrics = GatewayMetrics()
    gate = ActionPlanGate(metrics=metrics)

    now = int(time.time() * 1000)
    event = EventEnvelope(
        type=EventType.ACTION_PLAN,
        traceId="1" * 32,
        spanId="2" * 16,
        seq=1,
        tsCaptureMs=now,
        ttlMs=5000,
        coordFrame=CoordFrame.WORLD,
        confidence=0.9,
        priority=20,
        source="test@1.0",
        payload={
            "summary": "move forward",
            "plan": {
                "mode": "assist",
                "fallback": "scan",
                "steps": [
                    {"action": "move", "text": "move forward"},
                    {"action": "turn", "text": "turn right"},
                ],
            },
        },
    )

    gated = gate.gate_events([event], health_status="DEGRADED", health_reason="noncritical_timeout:real_depth")
    assert len(gated) == 1
    patched_plan = gated[0].payload.get("plan")
    assert isinstance(patched_plan, dict)
    steps = patched_plan.get("steps")
    assert isinstance(steps, list)
    actions = {str(item.get("action", "")).lower() for item in steps if isinstance(item, dict)}
    assert "move" not in actions
    assert "turn" not in actions
    assert "stop" in actions
    assert "scan" in actions

    samples = _parse_metrics(metrics.render().content.decode("utf-8", errors="ignore"))
    patch_delta = _metric_with_labels(samples, "byes_actiongate_patch_total", {"reason": "degraded_patch"})
    assert patch_delta > 0
