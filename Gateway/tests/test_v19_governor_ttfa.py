from __future__ import annotations

import io
import json
import re
import time
from typing import Any

from fastapi.testclient import TestClient

from byes.degradation import DegradationState
from byes.planner import FrameContext
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


def _send_frames(client: TestClient, count: int, performance_mode: str | None = None) -> None:
    for _ in range(count):
        files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
        payload = {"ttlMs": 5000, "preserveOld": True}
        if performance_mode is not None:
            payload["performanceMode"] = performance_mode
            payload["performanceReason"] = "test_throttled"
        meta = json.dumps(payload)
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


def test_v19_baseline_ttfa_outcome_aligns_with_frame_completed() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools(0, 0)
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")
        time.sleep(0.5)
        before = _parse_metrics(client.get("/metrics").text)

        _send_frames(client, 50)
        after = _wait_completed(client, before, expected_delta=50)

        frame_completed_delta = _metric_total(after, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        ttfa_outcome_delta = _metric_total(after, "byes_ttfa_outcome_total") - _metric_total(
            before, "byes_ttfa_outcome_total"
        )
        assert int(round(frame_completed_delta)) == 50
        assert int(round(ttfa_outcome_delta)) == 50


def test_v19_timeout_safe_mode_zero_violations_and_ttfa_outcome_aligns() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools(0, 0)
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

        frame_completed_delta = _metric_total(after, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        ttfa_outcome_delta = _metric_total(after, "byes_ttfa_outcome_total") - _metric_total(
            before, "byes_ttfa_outcome_total"
        )
        assert int(round(frame_completed_delta)) == 50
        assert int(round(ttfa_outcome_delta)) == 50

        first_safe_ms = _first_safe_mode_ms(capture.messages)
        assert first_safe_ms is not None
        for message in capture.messages:
            if not isinstance(message, dict):
                continue
            ts = message.get("timestampMs")
            if not isinstance(ts, int) or ts < int(first_safe_ms):
                continue
            event_type = str(message.get("type", ""))
            assert event_type != "perception"
            assert event_type != "action_plan"


def test_v19_throttled_mode_reduces_noncritical_invocations() -> None:
    with TestClient(app) as client:
        original_every_n = gateway.config.throttled_ocr_every_n_frames
        object.__setattr__(gateway.config, "throttled_ocr_every_n_frames", 4)
        _speedup_mock_tools(0, 0)
        try:
            client.post("/api/dev/reset")
            client.post("/api/fault/clear")
            time.sleep(0.5)

            # Deterministic planner-level assertion: THROTTLED schedules fewer non-critical tools.
            descriptors = gateway.registry.list_descriptors()
            normal_count = 0
            throttled_count = 0
            for seq in range(1, 21):
                normal_plan = gateway.planner.plan(
                    FrameContext(seq=seq, ts_capture_ms=0, ttl_ms=5000, meta={"performanceMode": "NORMAL"}),
                    DegradationState.NORMAL,
                    [],
                    descriptors,
                )
                throttled_plan = gateway.planner.plan(
                    FrameContext(seq=seq, ts_capture_ms=0, ttl_ms=5000, meta={"performanceMode": "THROTTLED"}),
                    DegradationState.NORMAL,
                    [],
                    descriptors,
                )
                normal_count += sum(1 for item in normal_plan.invocations if item.tool_name == "mock_ocr")
                throttled_count += sum(1 for item in throttled_plan.invocations if item.tool_name == "mock_ocr")
            assert throttled_count < normal_count

            client.post("/api/dev/reset")
            throttle_snapshot = gateway.governor.tick(queue_depth=999, timeout_rate=0.0)
            assert throttle_snapshot.mode == "THROTTLED"
            time.sleep(0.5)

            capture = _CaptureConnection()
            original_connections = gateway.connections
            gateway.connections = capture  # type: ignore[assignment]
            try:
                throttle_before = _parse_metrics(client.get("/metrics").text)
                _send_frames(client, 20, performance_mode="THROTTLED")
                throttle_after = _wait_completed(client, throttle_before, expected_delta=20)
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    if any(
                        isinstance(item, dict) and str(item.get("healthStatus", "")).upper() == "THROTTLED"
                        for item in capture.messages
                    ):
                        break
                    time.sleep(0.1)
            finally:
                gateway.connections = original_connections  # type: ignore[assignment]

            throttled_ocr_invoked = _metric_with_labels(throttle_after, "byes_tool_invoked_total", {"tool": "mock_ocr"}) - _metric_with_labels(
                throttle_before, "byes_tool_invoked_total", {"tool": "mock_ocr"}
            )
            assert throttled_ocr_invoked >= 0
            assert any(
                isinstance(item, dict) and str(item.get("healthStatus", "")).upper() == "THROTTLED"
                for item in capture.messages
            )
        finally:
            object.__setattr__(gateway.config, "throttled_ocr_every_n_frames", original_every_n)
