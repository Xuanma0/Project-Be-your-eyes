from __future__ import annotations

import io
import json
import re
import time
from typing import Any

from fastapi.testclient import TestClient

from byes.schema import CoordFrame, ToolResult, ToolStatus
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
            latencyMs=20,
            confidence=0.88,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={
                "text": "EXIT",
                "summary": "Detected text: EXIT",
                "lines": [{"text": "EXIT", "score": 0.88, "box": [0.1, 0.1, 0.3, 0.2]}],
                "task": "ocr",
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


def _safe_mode_window_violations(events: list[dict[str, Any]]) -> tuple[int, int]:
    safe_mode_seen = 0
    violations = 0
    safe_mode_active = False
    for evt in events:
        event_type = str(evt.get("type", ""))
        summary = str(evt.get("summary", "")).lower()
        if event_type == "health":
            if "safe_mode" in summary or "safe mode" in summary:
                safe_mode_seen += 1
                safe_mode_active = True
                continue
            if "gateway_normal" in summary or "gateway_degraded" in summary:
                safe_mode_active = False
                continue

        if safe_mode_active and event_type in {"perception", "action_plan"}:
            violations += 1
    return safe_mode_seen, violations


def test_real_ocr_timeout_enters_safemode_and_blocks_perception_actionplan() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        _ensure_stub_real_ocr()
        client.post("/api/dev/reset")
        client.post("/api/dev/intent", json={"intent": "scan_text", "durationMs": 20000})

        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            before = _parse_metrics(client.get("/metrics").text)
            set_fault = client.post("/api/fault/set", json={"tool": "real_ocr", "mode": "timeout", "value": True})
            assert set_fault.status_code == 200
            set_fault_mock = client.post("/api/fault/set", json={"tool": "mock_ocr", "mode": "timeout", "value": True})
            assert set_fault_mock.status_code == 200

            _send_frames(client, 50)
            after = _wait_completed(client, before, 50)
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
        real_ocr_timeout_delta = _metric_with_labels(
            after,
            "byes_tool_timeout_total",
            {"tool": "real_ocr"},
        ) - _metric_with_labels(
            before,
            "byes_tool_timeout_total",
            {"tool": "real_ocr"},
        )

        assert int(round(frame_received_delta)) == 50
        assert int(round(frame_completed_delta)) == 50
        assert int(round(e2e_count_delta)) == 50
        assert int(round(safemode_enter_delta)) == 1
        assert real_ocr_timeout_delta > 0

        safe_mode_seen, violations = _safe_mode_window_violations(capture.messages)
        assert safe_mode_seen >= 1
        assert violations == 0
