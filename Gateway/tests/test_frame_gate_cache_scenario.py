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
        self.messages.append({"receivedAtMs": int(time.time() * 1000), "event": obj})


class _StubRealDetTool(BaseTool):
    name = "real_det"
    version = "0.0.test"
    lane = ToolLane.SLOW
    capability = "det"
    degradable = True
    timeout_ms = 500
    p95_budget_ms = 300

    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        _ = ctx
        return ToolResult(
            toolName=self.name,
            toolVersion=self.version,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            latencyMs=8,
            confidence=0.85,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={
                "summary": "Detected person (cached)",
                "detections": [{"class": "person", "bbox": [0.2, 0.2, 0.6, 0.9], "confidence": 0.85}],
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
    key = tuple(sorted(labels.items(), key=lambda item: item[0]))
    return samples.get((name, key), 0.0)


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


def _expired_emitted_events(messages: list[dict[str, Any]]) -> int:
    expired = 0
    for item in messages:
        received_at_ms = item.get("receivedAtMs")
        event = item.get("event")
        if not isinstance(received_at_ms, int) or not isinstance(event, dict):
            continue
        ts_ms = event.get("timestampMs")
        ttl_ms = event.get("ttlMs")
        if isinstance(ts_ms, int) and isinstance(ttl_ms, int):
            if ttl_ms <= 0 or (received_at_ms - ts_ms) > ttl_ms:
                expired += 1
    return expired


def test_cache_scenario_repeat_frame_keeps_frame_accounting_and_limits_slow_tool() -> None:
    with TestClient(app) as client:
        gateway.registry.register(_StubRealDetTool())
        client.post("/api/dev/reset")

        capture = _CaptureConnection()
        original_connections = gateway.connections
        gateway.connections = capture  # type: ignore[assignment]
        try:
            before = _parse_metrics(client.get("/metrics").text)
            image_bytes = b"same_frame_bytes_for_cache_test"
            for _ in range(50):
                files = {"image": ("frame.jpg", io.BytesIO(image_bytes), "image/jpeg")}
                meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
                response = client.post("/api/frame", files=files, data={"meta": meta})
                assert response.status_code == 200

            after = _wait_completed(client, before, 50)
        finally:
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
        real_det_invoked_delta = _metric_with_labels(
            after, "byes_tool_invoked_total", {"tool": "real_det"}
        ) - _metric_with_labels(
            before, "byes_tool_invoked_total", {"tool": "real_det"}
        )
        real_ocr_invoked_delta = _metric_with_labels(
            after, "byes_tool_invoked_total", {"tool": "real_ocr"}
        ) - _metric_with_labels(
            before, "byes_tool_invoked_total", {"tool": "real_ocr"}
        )
        cache_hit_delta = _metric_with_labels(
            after, "byes_tool_cache_hit_total", {"tool": "real_det"}
        ) - _metric_with_labels(
            before, "byes_tool_cache_hit_total", {"tool": "real_det"}
        )

        assert int(round(frame_received_delta)) == 50
        assert int(round(frame_completed_delta)) == 50
        assert int(round(e2e_count_delta)) == 50
        assert 1 <= int(round(real_det_invoked_delta)) <= 10
        assert int(round(real_ocr_invoked_delta)) == 0
        assert cache_hit_delta > 0
        assert _expired_emitted_events(capture.messages) == 0
