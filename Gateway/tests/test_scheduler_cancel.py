from __future__ import annotations

import asyncio

import pytest

from byes.config import GatewayConfig
from byes.scheduler import Scheduler
from byes.schema import CoordFrame, ToolResult, ToolStatus
from byes.tool_registry import ToolRegistry
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane


class SlowRiskTool(BaseTool):
    name = "slow_risk"
    version = "1.0.0"
    lane = ToolLane.FAST
    capability = "risk"
    degradable = False
    timeout_ms = 1000
    p95_budget_ms = 800

    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        _ = ctx
        await asyncio.sleep(0.25)
        return ToolResult(
            toolName=self.name,
            toolVersion=self.version,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            latencyMs=250,
            confidence=0.9,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={"riskText": f"risk-{frame.seq}"},
        )


def make_config() -> GatewayConfig:
    return GatewayConfig(
        send_envelope=False,
        default_ttl_ms=2000,
        risk_priority=100,
        perception_priority=10,
        navigation_priority=20,
        dialog_priority=30,
        health_priority=90,
        low_confidence_threshold=0.6,
        fast_lane_deadline_ms=800,
        slow_lane_deadline_ms=1500,
        fast_q_maxsize=16,
        slow_q_maxsize=16,
        slow_q_drop_threshold=16,
        timeout_rate_threshold=0.35,
        timeout_window_size=20,
        safe_mode_without_ws_client=False,
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
        mock_tool_timeout_ms=1200,
    )


@pytest.mark.asyncio
async def test_new_frame_cancels_previous_active_task() -> None:
    registry = ToolRegistry()
    registry.register(SlowRiskTool())

    statuses_by_seq: dict[int, list[ToolStatus]] = {}

    async def on_lane_results(frame: FrameInput, lane: ToolLane, results: list[ToolResult]) -> None:
        _ = lane
        statuses_by_seq.setdefault(frame.seq, []).extend([item.status for item in results])

    scheduler = Scheduler(config=make_config(), registry=registry, on_lane_results=on_lane_results)
    await scheduler.start()

    seq1 = await scheduler.submit_frame(
        frame_bytes=b"f1",
        meta={"ttlMs": 2000},
        trace_id="a" * 32,
        span_id="b" * 16,
    )
    await asyncio.sleep(0.05)
    seq2 = await scheduler.submit_frame(
        frame_bytes=b"f2",
        meta={"ttlMs": 2000},
        trace_id="a" * 32,
        span_id="b" * 16,
    )

    await asyncio.sleep(0.6)
    await scheduler.stop()

    assert seq2 in statuses_by_seq
    assert ToolStatus.OK in statuses_by_seq[seq2]

    if seq1 in statuses_by_seq:
        assert ToolStatus.OK not in statuses_by_seq[seq1]
