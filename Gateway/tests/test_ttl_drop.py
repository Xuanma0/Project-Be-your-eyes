from __future__ import annotations

import asyncio
import time

import pytest

from byes.config import GatewayConfig
from byes.scheduler import Scheduler
from byes.tool_registry import ToolRegistry
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane
from byes.schema import CoordFrame, ToolResult, ToolStatus


class InstantRiskTool(BaseTool):
    name = "instant_risk"
    version = "1.0.0"
    lane = ToolLane.FAST
    capability = "risk"
    degradable = False
    timeout_ms = 200
    p95_budget_ms = 100

    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        _ = ctx
        return ToolResult(
            toolName=self.name,
            toolVersion=self.version,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            latencyMs=1,
            confidence=0.9,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={"riskText": "Obstacle ahead"},
        )


def make_config() -> GatewayConfig:
    return GatewayConfig(
        send_envelope=False,
        default_ttl_ms=50,
        risk_priority=100,
        perception_priority=10,
        navigation_priority=20,
        dialog_priority=30,
        health_priority=90,
        low_confidence_threshold=0.6,
        fast_lane_deadline_ms=100,
        slow_lane_deadline_ms=300,
        fast_q_maxsize=8,
        slow_q_maxsize=8,
        slow_q_drop_threshold=8,
        timeout_rate_threshold=0.5,
        timeout_window_size=10,
        safe_mode_without_ws_client=False,
        ws_disconnect_grace_ms=3000,
        ws_no_client_warn_interval_ms=5000,
        mock_risk_delay_ms=0,
        mock_risk_confidence=0.9,
        mock_risk_distance_m=1.0,
        mock_risk_azimuth_deg=0.0,
        mock_risk_text="Obstacle ahead",
        mock_ocr_delay_ms=0,
        mock_ocr_confidence=0.8,
        mock_ocr_text="Door detected",
        mock_tool_timeout_ms=200,
    )


@pytest.mark.asyncio
async def test_scheduler_drops_expired_frame_by_ttl() -> None:
    registry = ToolRegistry()
    registry.register(InstantRiskTool())
    seen: list[tuple[int, ToolLane]] = []

    async def on_lane_results(frame: FrameInput, lane: ToolLane, results: list[ToolResult]) -> None:
        _ = results
        seen.append((frame.seq, lane))

    scheduler = Scheduler(config=make_config(), registry=registry, on_lane_results=on_lane_results)
    await scheduler.start()

    ts_capture_ms = int(time.time() * 1000) - 500
    await scheduler.submit_frame(
        frame_bytes=b"x",
        meta={"tsCaptureMs": ts_capture_ms, "ttlMs": 10},
        trace_id="0" * 32,
        span_id="0" * 16,
    )

    await asyncio.sleep(0.1)
    await scheduler.stop()

    assert seen == []
