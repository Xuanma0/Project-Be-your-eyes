from __future__ import annotations

import asyncio
import io
import re
import time
from typing import Any

import pytest
from PIL import Image

from byes.config import GatewayConfig
from byes.frame_tracker import FrameTracker
from byes.metrics import GatewayMetrics
from byes.planner import ToolInvocation, ToolInvocationPlan
from byes.preprocess import FramePreprocessor
from byes.scheduler import Scheduler, _QueuedTask
from byes.schema import CoordFrame, ToolResult, ToolStatus
from byes.tool_registry import ToolRegistry
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


def _cfg() -> GatewayConfig:
    return GatewayConfig(
        send_envelope=False,
        default_ttl_ms=3000,
        risk_priority=100,
        perception_priority=10,
        navigation_priority=20,
        dialog_priority=30,
        health_priority=90,
        low_confidence_threshold=0.6,
        fast_lane_deadline_ms=500,
        slow_lane_deadline_ms=1200,
        fast_q_maxsize=16,
        slow_q_maxsize=16,
        slow_q_drop_threshold=16,
        timeout_rate_threshold=0.35,
        timeout_window_size=20,
        safe_mode_without_ws_client=True,
        ws_disconnect_grace_ms=3000,
        ws_no_client_warn_interval_ms=5000,
        mock_risk_delay_ms=0,
        mock_risk_confidence=0.9,
        mock_risk_distance_m=1.5,
        mock_risk_azimuth_deg=0.0,
        mock_risk_text="Obstacle ahead",
        mock_ocr_delay_ms=0,
        mock_ocr_confidence=0.8,
        mock_ocr_text="Door detected",
        mock_tool_timeout_ms=1000,
        det_max_side=640,
        ocr_max_side=1280,
        depth_max_side=640,
        det_jpeg_quality=75,
        ocr_jpeg_quality=80,
        depth_jpeg_quality=75,
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


def _image_bytes(width: int = 640, height: int = 360, color: tuple[int, int, int] = (120, 20, 10)) -> bytes:
    buf = io.BytesIO()
    image = Image.new("RGB", (width, height), color=color)
    image.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


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


def _metric_total(samples: dict[SeriesKey, float], name: str) -> float:
    return sum(value for (metric_name, _labels), value in samples.items() if metric_name == name)


class _CaptureTool(BaseTool):
    version = "test"
    lane = ToolLane.SLOW
    p95_budget_ms = 200
    timeout_ms = 500
    degradable = True

    def __init__(self, name: str, capability: str) -> None:
        self.name = name
        self.capability = capability
        self.last_frame_bytes: bytes | None = None

    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        _ = ctx
        self.last_frame_bytes = frame.frame_bytes
        return ToolResult(
            toolName=self.name,
            toolVersion=self.version,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            latencyMs=1,
            confidence=0.8,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={"summary": f"{self.name} ok"},
        )


def test_preprocess_builds_variants_and_caches() -> None:
    cfg = _cfg()
    metrics = GatewayMetrics()
    tracker = FrameTracker(metrics=metrics, now_ms_fn=_now_ms)
    preprocessor = FramePreprocessor(cfg)
    raw = _image_bytes()

    tracker.start_frame(seq=1, received_at_ms=_now_ms(), ttl_ms=5000)
    first = tracker.get_or_build_artifacts(seq=1, frame_bytes=raw, meta={"ttlMs": 5000}, preprocessor=preprocessor)
    second = tracker.get_or_build_artifacts(seq=1, frame_bytes=raw, meta={"ttlMs": 5000}, preprocessor=preprocessor)

    assert first.det_jpeg_bytes
    assert first.ocr_jpeg_bytes
    assert first.depth_jpeg_bytes
    assert second is first
    samples = _parse_metrics(metrics.render().content.decode("utf-8", errors="ignore"))
    assert int(round(_metric_total(samples, "byes_preprocess_cache_hit_total"))) >= 1


def test_preprocess_decode_error_fallback() -> None:
    cfg = _cfg()
    metrics = GatewayMetrics()
    tracker = FrameTracker(metrics=metrics, now_ms_fn=_now_ms)
    preprocessor = FramePreprocessor(cfg)
    raw = b"\x01\x02\x03\x04\x05invalid-image"

    tracker.start_frame(seq=2, received_at_ms=_now_ms(), ttl_ms=5000)
    artifacts = tracker.get_or_build_artifacts(seq=2, frame_bytes=raw, meta={"ttlMs": 5000}, preprocessor=preprocessor)

    assert artifacts.decode_error is True
    assert artifacts.det_jpeg_bytes == raw
    assert artifacts.ocr_jpeg_bytes == raw
    assert artifacts.depth_jpeg_bytes == raw
    samples = _parse_metrics(metrics.render().content.decode("utf-8", errors="ignore"))
    assert int(round(_metric_total(samples, "byes_preprocess_decode_error_total"))) >= 1


@pytest.mark.asyncio
async def test_tool_uses_expected_variant() -> None:
    cfg = _cfg()
    metrics = GatewayMetrics()
    tracker = FrameTracker(metrics=metrics, now_ms_fn=_now_ms)
    preprocessor = FramePreprocessor(cfg)
    registry = ToolRegistry()
    det_tool = _CaptureTool("real_det", "det")
    ocr_tool = _CaptureTool("real_ocr", "ocr")
    depth_tool = _CaptureTool("real_depth", "depth")
    registry.register(det_tool)
    registry.register(ocr_tool)
    registry.register(depth_tool)

    async def _on_lane_results(frame: FrameInput, lane: ToolLane, results: list[ToolResult]) -> None:
        _ = frame
        _ = lane
        _ = results

    scheduler = Scheduler(
        config=cfg,
        registry=registry,
        on_lane_results=_on_lane_results,
        metrics=metrics,
        frame_tracker=tracker,
        preprocessor=preprocessor,
    )
    raw = _image_bytes(width=320, height=240, color=(10, 50, 90))
    frame = FrameInput(
        seq=10,
        ts_capture_ms=_now_ms(),
        ttl_ms=5000,
        frame_bytes=raw,
        meta={"ttlMs": 5000, "preserveOld": True, "intent": "scan_text", "fingerprint": "fp"},
    )
    tracker.start_frame(seq=10, received_at_ms=_now_ms(), ttl_ms=5000)
    scheduler._plan_by_seq[10] = ToolInvocationPlan(
        seq=10,
        generated_at_ms=_now_ms(),
        fast_budget_ms=cfg.fast_budget_ms,
        slow_budget_ms=cfg.slow_budget_ms,
        invocations=[
            ToolInvocation(tool_name="real_det", lane=ToolLane.SLOW, timeout_ms=300, priority=300, input_variant="det"),
            ToolInvocation(tool_name="real_ocr", lane=ToolLane.SLOW, timeout_ms=300, priority=250, input_variant="ocr"),
            ToolInvocation(tool_name="real_depth", lane=ToolLane.SLOW, timeout_ms=300, priority=240, input_variant="depth"),
        ],
    )
    queued = _QueuedTask(frame=frame, trace_id="a" * 32, span_id="b" * 16)

    results = await scheduler._run_tools_for_lane(queued, ToolLane.SLOW)
    assert len(results) == 3
    artifacts = tracker.get_or_build_artifacts(seq=10, frame_bytes=raw, meta=frame.meta, preprocessor=preprocessor)
    assert det_tool.last_frame_bytes == artifacts.det_jpeg_bytes
    assert ocr_tool.last_frame_bytes == artifacts.ocr_jpeg_bytes
    assert depth_tool.last_frame_bytes == artifacts.depth_jpeg_bytes
