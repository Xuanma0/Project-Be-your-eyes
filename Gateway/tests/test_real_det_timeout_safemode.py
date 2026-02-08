from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx
import pytest

from byes.config import GatewayConfig
from byes.degradation import DegradationManager
from byes.frame_tracker import FrameTracker
from byes.fusion import FusionEngine
from byes.metrics import GatewayMetrics
from byes.safety import SafetyKernel
from byes.scheduler import Scheduler
from byes.schema import EventType, ToolResult
from byes.tool_registry import ToolRegistry
from byes.tools import MockOcrTool, MockRiskTool, RealDetTool
from byes.tools.base import FrameInput, ToolLane

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


class _TimeoutRunner:
    async def infer_bundle(self, request, timeout_ms):  # noqa: ANN001, ANN201
        _ = request
        _ = timeout_ms
        raise httpx.ReadTimeout("real_det timeout")


def _cfg() -> GatewayConfig:
    return GatewayConfig(
        send_envelope=False,
        default_ttl_ms=5000,
        risk_priority=100,
        perception_priority=10,
        navigation_priority=20,
        dialog_priority=30,
        health_priority=90,
        low_confidence_threshold=0.6,
        fast_lane_deadline_ms=500,
        slow_lane_deadline_ms=800,
        fast_q_maxsize=64,
        slow_q_maxsize=64,
        slow_q_drop_threshold=64,
        timeout_rate_threshold=0.25,
        timeout_window_size=6,
        safe_mode_without_ws_client=False,
        ws_disconnect_grace_ms=3000,
        ws_no_client_warn_interval_ms=5000,
        mock_risk_delay_ms=30,
        mock_risk_confidence=0.9,
        mock_risk_distance_m=1.5,
        mock_risk_azimuth_deg=0.0,
        mock_risk_text="Obstacle ahead",
        mock_ocr_delay_ms=150,
        mock_ocr_confidence=0.8,
        mock_ocr_text="Door detected",
        mock_tool_timeout_ms=1000,
        frame_tracker_retention_ms=120000,
        frame_tracker_max_entries=20000,
        enable_real_det=True,
        real_det_endpoint="http://127.0.0.1:9001/infer",
        real_det_timeout_ms=80,
        real_det_p95_budget_ms=60,
        real_det_max_inflight=2,
        real_det_queue_policy="drop",
    )


def _parse_metrics(text: str) -> dict[SeriesKey, float]:
    rows: dict[SeriesKey, float] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _METRIC_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        labels_raw = m.group(2)
        value_raw = m.group(3)
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
    return sum(value for (metric, _labels), value in samples.items() if metric == name)


def _now_ms() -> int:
    return int(time.time() * 1000)


@pytest.mark.asyncio
async def test_real_det_timeout_enters_safemode_and_preserves_per_frame_e2e() -> None:
    cfg = _cfg()
    metrics = GatewayMetrics()
    registry = ToolRegistry()
    degradation = DegradationManager(cfg, metrics)
    frame_tracker = FrameTracker(metrics=metrics, now_ms_fn=_now_ms)
    fusion = FusionEngine(cfg)
    safety = SafetyKernel(cfg, degradation)

    risk = MockRiskTool(cfg)
    ocr = MockOcrTool(cfg)
    det = RealDetTool(cfg)
    det._runner = _TimeoutRunner()  # type: ignore[attr-defined]

    registry.register(risk)
    registry.register(ocr)
    registry.register(det)

    emitted: list[dict[str, Any]] = []

    async def on_lane_results(frame: FrameInput, lane: ToolLane, results: list[ToolResult]) -> None:
        fused = fusion.fuse_lane(frame=frame, lane=lane, results=results, trace_id="0" * 32, span_id="0" * 16)
        now_ms = _now_ms()
        decision = safety.adjudicate(fused.events, now_ms=now_ms)
        emitted_count = 0
        for event in decision.events:
            if event.is_expired(now_ms):
                metrics.inc_deadline_miss(lane.value)
                continue
            safe_mode_now = degradation.is_safe_mode()
            if safe_mode_now and event.type == EventType.PERCEPTION:
                continue
            emitted.append(
                {
                    "ts": now_ms,
                    "type": event.type.value,
                    "seq": event.seq,
                    "safe_mode": safe_mode_now,
                }
            )
            emitted_count += 1

        if emitted_count > 0:
            frame_tracker.complete_frame(frame.seq, "ok", now_ms)
        elif lane == ToolLane.FAST:
            frame_tracker.complete_frame(
                frame.seq,
                "safemode_suppressed" if degradation.is_safe_mode() else "error",
                now_ms,
            )

    def on_frame_terminal(frame: FrameInput, outcome: str) -> None:
        frame_tracker.complete_frame(frame.seq, outcome, _now_ms())

    scheduler = Scheduler(
        config=cfg,
        registry=registry,
        on_lane_results=on_lane_results,
        metrics=metrics,
        degradation_manager=degradation,
        on_frame_terminal=on_frame_terminal,
    )

    await scheduler.start()
    total_frames = 50
    baseline_metrics = _parse_metrics(metrics.render().content.decode("utf-8", errors="ignore"))
    for _ in range(total_frames):
        seq = await scheduler.submit_frame(
            frame_bytes=b"frame",
            meta={"ttlMs": 5000, "preserveOld": True},
            trace_id="a" * 32,
            span_id="b" * 16,
        )
        frame_tracker.start_frame(seq, _now_ms(), 5000)

    deadline = time.time() + 20.0
    while time.time() < deadline:
        current = _parse_metrics(metrics.render().content.decode("utf-8", errors="ignore"))
        completed_delta = _metric_total(current, "byes_frame_completed_total") - _metric_total(
            baseline_metrics, "byes_frame_completed_total"
        )
        if completed_delta >= total_frames:
            break
        await asyncio.sleep(0.1)

    await scheduler.stop()

    after = _parse_metrics(metrics.render().content.decode("utf-8", errors="ignore"))
    frame_received_delta = _metric_total(after, "byes_frame_received_total") - _metric_total(
        baseline_metrics, "byes_frame_received_total"
    )
    frame_completed_delta = _metric_total(after, "byes_frame_completed_total") - _metric_total(
        baseline_metrics, "byes_frame_completed_total"
    )
    e2e_count_delta = _metric_total(after, "byes_e2e_latency_ms_count") - _metric_total(
        baseline_metrics, "byes_e2e_latency_ms_count"
    )
    safemode_enter_delta = _metric_total(after, "byes_safemode_enter_total") - _metric_total(
        baseline_metrics, "byes_safemode_enter_total"
    )

    assert int(round(frame_received_delta)) == total_frames
    assert int(round(frame_completed_delta)) == total_frames
    assert int(round(e2e_count_delta)) == total_frames
    assert safemode_enter_delta >= 1

    safe_mode_perception = [item for item in emitted if item["safe_mode"] and item["type"] == EventType.PERCEPTION.value]
    assert safe_mode_perception == []
    assert any(item["type"] == EventType.RISK.value for item in emitted)
