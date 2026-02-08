from __future__ import annotations

import io
import json
import re
import time
from typing import Any

from fastapi.testclient import TestClient

from byes.schema import CoordFrame, ToolResult, ToolStatus
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane
from byes.tools.real_ocr import RealOcrTool
from main import app, gateway

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


class _CaptureConnection:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def broadcast_json(self, obj: dict[str, Any]) -> None:
        self.messages.append(obj)


class _StubRealOcrTool(RealOcrTool):
    async def infer(self, frame, ctx):  # noqa: ANN001, ANN201
        _ = ctx
        return ToolResult(
            toolName=self.name,
            toolVersion=self.version,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            latencyMs=15,
            confidence=0.9,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={
                "text": "EXIT",
                "summary": "Detected text: EXIT",
                "lines": [{"text": "EXIT", "score": 0.9, "box": [0.1, 0.2, 0.3, 0.4]}],
                "task": "ocr",
            },
        )


class _NeutralRealDetTool(BaseTool):
    name = "real_det"
    version = "0.0.test"
    lane = ToolLane.SLOW
    capability = "det"
    degradable = True
    timeout_ms = 500
    p95_budget_ms = 300

    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        _ = frame
        _ = ctx
        return ToolResult(
            toolName=self.name,
            toolVersion=self.version,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            latencyMs=5,
            confidence=0.2,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={
                "summary": "det ready",
                "detections": [{"class": "poster", "bbox": [0.1, 0.1, 0.2, 0.2], "confidence": 0.2}],
            },
        )


def _speedup_mock_tools() -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = 0
    ocr = gateway.registry.get("mock_ocr")
    if ocr is not None and hasattr(ocr, "_delay_ms"):
        ocr._delay_ms = 0


def _ensure_stub_real_ocr() -> None:
    gateway.registry.register(_StubRealOcrTool(gateway.config))
    gateway.registry.register(_NeutralRealDetTool())


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
        time.sleep(0.03)


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


def _wait_metric_delta_positive(
    client: TestClient,
    before: dict[SeriesKey, float],
    metric_name: str,
    labels: dict[str, str],
    timeout_sec: float = 8.0,
) -> dict[SeriesKey, float]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        current = _parse_metrics(client.get("/metrics").text)
        delta = _metric_with_labels(current, metric_name, labels) - _metric_with_labels(before, metric_name, labels)
        if delta > 0:
            return current
        time.sleep(0.1)
    return _parse_metrics(client.get("/metrics").text)


def test_real_ocr_scan_intent_gates_invocation_and_emits_perception_actionplan() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        _ensure_stub_real_ocr()
        client.post("/api/dev/reset")

        baseline_before = _parse_metrics(client.get("/metrics").text)
        _send_frames(client, 10)
        baseline_after = _wait_completed(client, baseline_before, 10)

        baseline_invoked_delta = _metric_with_labels(
            baseline_after, "byes_tool_invoked_total", {"tool": "real_ocr"}
        ) - _metric_with_labels(
            baseline_before, "byes_tool_invoked_total", {"tool": "real_ocr"}
        )
        assert baseline_invoked_delta == 0

        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            intent_resp = client.post("/api/dev/intent", json={"intent": "scan_text", "durationMs": 8000})
            assert intent_resp.status_code == 200
            assert intent_resp.json().get("intent") == "scan_text"

            scan_before = _parse_metrics(client.get("/metrics").text)
            _send_frames(client, 20)
            _ = _wait_completed(client, scan_before, 20)
            scan_after = _wait_metric_delta_positive(
                client,
                scan_before,
                "byes_tool_invoked_total",
                {"tool": "real_ocr"},
            )
        finally:
            gateway.connections = original_connections  # type: ignore[assignment]

        scan_invoked_delta = _metric_with_labels(
            scan_after, "byes_tool_invoked_total", {"tool": "real_ocr"}
        ) - _metric_with_labels(
            scan_before, "byes_tool_invoked_total", {"tool": "real_ocr"}
        )
        assert scan_invoked_delta > 0

        emitted_types = [str(item.get("type")) for item in capture.messages if isinstance(item, dict)]
        assert "perception" in emitted_types
        assert "action_plan" in emitted_types
