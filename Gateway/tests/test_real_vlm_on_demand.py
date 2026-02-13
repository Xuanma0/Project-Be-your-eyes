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


class _StubRealVlmTool(BaseTool):
    name = "real_vlm"
    version = "0.0.test"
    lane = ToolLane.SLOW
    capability = "vlm"
    degradable = True
    timeout_ms = 600
    p95_budget_ms = 450

    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        _ = ctx
        question = str(frame.meta.get("intentQuestion", "what is in front of me?")).strip()
        return ToolResult(
            toolName=self.name,
            toolVersion=self.version,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            latencyMs=12,
            confidence=0.86,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={
                "answerText": "Doorway ahead.",
                "actionPlan": {
                    "summary": "VLM says doorway ahead",
                    "speech": f"Question: {question}. Doorway ahead.",
                    "hud": ["Doorway ahead", "Confirm before moving"],
                    "confidence": 0.86,
                    "tags": ["real_vlm", "ask"],
                    "steps": [
                        {"action": "confirm", "text": "Confirm doorway is clear."},
                        {"action": "scan", "text": "Scan left and right."},
                    ],
                    "fallback": "confirm",
                    "mode": "ask",
                },
                "summary": "VLM says doorway ahead",
                "task": "vlm",
            },
        )


def _speedup_mock_tools() -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = 0
    ocr = gateway.registry.get("mock_ocr")
    if ocr is not None and hasattr(ocr, "_delay_ms"):
        ocr._delay_ms = 0


def _ensure_stub_real_vlm() -> None:
    gateway.registry.register(_StubRealVlmTool())


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
    key = tuple(sorted(labels.items(), key=lambda item: item[0]))
    return samples.get((name, key), 0.0)


def _send_frames(client: TestClient, count: int) -> None:
    for _ in range(count):
        files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
        meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
        resp = client.post("/api/frame", files=files, data={"meta": meta})
        assert resp.status_code == 200


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


def _wait_metric_delta_positive(
    client: TestClient,
    before: dict[SeriesKey, float],
    metric_name: str,
    labels: dict[str, str],
    timeout_sec: float = 10.0,
) -> dict[SeriesKey, float]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        current = _parse_metrics(client.get("/metrics").text)
        delta = _metric_with_labels(current, metric_name, labels) - _metric_with_labels(before, metric_name, labels)
        if delta > 0:
            return current
        time.sleep(0.1)
    return _parse_metrics(client.get("/metrics").text)


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


def test_real_vlm_baseline_off_and_ask_on_demand() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        _ensure_stub_real_vlm()
        client.post("/api/dev/reset")

        baseline_before = _parse_metrics(client.get("/metrics").text)
        _send_frames(client, 10)
        baseline_after = _wait_completed(client, baseline_before, 10)

        baseline_invoked_delta = _metric_with_labels(
            baseline_after, "byes_tool_invoked_total", {"tool": "real_vlm"}
        ) - _metric_with_labels(
            baseline_before, "byes_tool_invoked_total", {"tool": "real_vlm"}
        )
        assert baseline_invoked_delta == 0

        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            intent_resp = client.post(
                "/api/dev/intent",
                json={"kind": "ask", "question": "what is in front of me?", "durationMs": 8000},
            )
            assert intent_resp.status_code == 200
            ask_before = _parse_metrics(client.get("/metrics").text)
            _send_frames(client, 20)
            _ = _wait_completed(client, ask_before, 20)
            ask_after = _wait_metric_delta_positive(
                client,
                ask_before,
                "byes_tool_invoked_total",
                {"tool": "real_vlm"},
            )
        finally:
            gateway.connections = original_connections  # type: ignore[assignment]

        ask_invoked_delta = _metric_with_labels(
            ask_after, "byes_tool_invoked_total", {"tool": "real_vlm"}
        ) - _metric_with_labels(
            ask_before, "byes_tool_invoked_total", {"tool": "real_vlm"}
        )
        assert ask_invoked_delta > 0

        emitted_types = [str(item.get("type")) for item in capture.messages if isinstance(item, dict)]
        assert "action_plan" in emitted_types


def test_real_vlm_safemode_blocks_actionplan_output() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        _ensure_stub_real_vlm()
        client.post("/api/dev/reset")

        intent_resp = client.post(
            "/api/dev/intent",
            json={"kind": "ask", "question": "what is in front of me?", "durationMs": 20000},
        )
        assert intent_resp.status_code == 200

        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            before = _parse_metrics(client.get("/metrics").text)
            set_fault = client.post("/api/fault/set", json={"tool": "mock_risk", "mode": "timeout", "value": True})
            assert set_fault.status_code == 200
            _send_frames(client, 50)
            _ = _wait_completed(client, before, 50)
            after = _wait_metric_delta_positive(
                client,
                before,
                "byes_tool_skipped_total",
                {"tool": "real_vlm", "reason": "safe_mode"},
            )
        finally:
            client.post("/api/fault/clear")
            gateway.connections = original_connections  # type: ignore[assignment]

        frame_received_delta = _metric_total(after, "byes_frame_received_total") - _metric_total(
            before, "byes_frame_received_total"
        )
        frame_completed_delta = _metric_total(after, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        e2e_count_delta = _metric_total(after, "byes_e2e_latency_ms_count") - _metric_total(
            before, "byes_e2e_latency_ms_count"
        )
        safemode_enter_delta = _metric_total(after, "byes_safemode_enter_total") - _metric_total(
            before, "byes_safemode_enter_total"
        )
        real_vlm_skipped_safemode_delta = _metric_with_labels(
            after,
            "byes_tool_skipped_total",
            {"tool": "real_vlm", "reason": "safe_mode"},
        ) - _metric_with_labels(
            before,
            "byes_tool_skipped_total",
            {"tool": "real_vlm", "reason": "safe_mode"},
        )

        assert int(round(frame_received_delta)) == 50
        assert int(round(frame_completed_delta)) == 50
        assert int(round(e2e_count_delta)) == 50
        assert safemode_enter_delta >= 1
        assert real_vlm_skipped_safemode_delta > 0

        first_safe_mode_ms = _first_safe_mode_ms(capture.messages)
        assert first_safe_mode_ms is not None

        for message in capture.messages:
            if not isinstance(message, dict):
                continue
            timestamp_ms = message.get("timestampMs")
            if not isinstance(timestamp_ms, int) or timestamp_ms < int(first_safe_mode_ms):
                continue
            event_type = str(message.get("type", ""))
            assert event_type != "perception"
            assert event_type != "action_plan"
