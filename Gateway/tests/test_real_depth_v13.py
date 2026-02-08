from __future__ import annotations

import io
import json
import re
import time
from typing import Any

from fastapi.testclient import TestClient

from byes.schema import CoordFrame, ToolResult, ToolStatus
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane
from main import app, gateway

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


class _CaptureConnection:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def broadcast_json(self, obj: dict[str, Any]) -> None:
        self.messages.append(obj)


class _StubRealDepthTool(BaseTool):
    name = "real_depth"
    version = "0.0.test"
    lane = ToolLane.SLOW
    capability = "depth"
    degradable = True
    timeout_ms = 700
    p95_budget_ms = 500

    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        _ = frame
        _ = ctx
        return ToolResult(
            toolName=self.name,
            toolVersion=self.version,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            latencyMs=30,
            confidence=0.88,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={
                "hazards": [
                    {"distanceM": 1.2, "azimuthDeg": 5.0, "confidence": 0.88, "kind": "obstacle"},
                ],
                "model": "stub_depth",
                "summary": "Depth hazard: obstacle at 1.20m",
            },
        )


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


def _wait_completed(client: TestClient, before: dict[SeriesKey, float], expected_delta: int) -> dict[SeriesKey, float]:
    deadline = time.time() + 25.0
    while time.time() < deadline:
        current = _parse_metrics(client.get("/metrics").text)
        completed = _metric_total(current, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        if completed >= expected_delta:
            return current
        time.sleep(0.1)
    return _parse_metrics(client.get("/metrics").text)


def _send_frames(client: TestClient, count: int) -> None:
    for _ in range(count):
        files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
        meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
        resp = client.post("/api/frame", files=files, data={"meta": meta})
        assert resp.status_code == 200


def _speedup_mock_tools() -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = 0
    ocr = gateway.registry.get("mock_ocr")
    if ocr is not None and hasattr(ocr, "_delay_ms"):
        ocr._delay_ms = 0


def test_real_depth_baseline_invoked() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        gateway.registry.register(_StubRealDepthTool())
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
        real_depth_invoked_delta = _metric_with_labels(after, "byes_tool_invoked_total", {"tool": "real_depth"}) - _metric_with_labels(
            before,
            "byes_tool_invoked_total",
            {"tool": "real_depth"},
        )

        assert int(round(frame_received_delta)) == 50
        assert int(round(frame_completed_delta)) == 50
        assert int(round(e2e_count_delta)) == 50
        assert real_depth_invoked_delta > 0


def test_real_depth_timeout_noncritical_no_safemode() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        gateway.registry.register(_StubRealDepthTool())
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")
        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            before = _parse_metrics(client.get("/metrics").text)
            set_fault = client.post("/api/fault/set", json={"tool": "real_depth", "mode": "timeout", "value": True})
            assert set_fault.status_code == 200
            _send_frames(client, 50)
            after = _wait_completed(client, before, expected_delta=50)
        finally:
            client.post("/api/fault/clear")
            gateway.connections = original_connections  # type: ignore[assignment]

        safemode_delta = _metric_total(after, "byes_safemode_enter_total") - _metric_total(before, "byes_safemode_enter_total")
        real_depth_timeout_delta = _metric_with_labels(after, "byes_tool_timeout_total", {"tool": "real_depth"}) - _metric_with_labels(
            before,
            "byes_tool_timeout_total",
            {"tool": "real_depth"},
        )
        degraded_delta = sum(
            value
            for (name, labels), value in after.items()
            if name == "byes_degradation_state_change_total" and dict(labels).get("to_state") == "DEGRADED"
        ) - sum(
            value
            for (name, labels), value in before.items()
            if name == "byes_degradation_state_change_total" and dict(labels).get("to_state") == "DEGRADED"
        )

        assert int(round(safemode_delta)) == 0
        assert real_depth_timeout_delta > 0
        assert degraded_delta > 0


def test_critical_timeout_enters_safemode() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        gateway.registry.register(_StubRealDepthTool())
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

        safemode_delta = _metric_total(after, "byes_safemode_enter_total") - _metric_total(before, "byes_safemode_enter_total")
        emitted_types = {
            str(item.get("type"))
            for item in capture.messages
            if isinstance(item, dict) and item.get("type") is not None
        }
        assert int(round(safemode_delta)) == 1
        assert "perception" not in emitted_types
        assert "action_plan" not in emitted_types
        assert emitted_types.issubset({"risk", "health"})
