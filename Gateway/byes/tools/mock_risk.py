from __future__ import annotations

import asyncio
import time

from byes.config import GatewayConfig
from byes.schema import CoordFrame, ToolResult, ToolStatus
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane


class MockRiskTool(BaseTool):
    name = "mock_risk"
    version = "1.0.0"
    lane = ToolLane.FAST
    capability = "risk"
    degradable = False

    def __init__(self, config: GatewayConfig) -> None:
        self.timeout_ms = config.mock_tool_timeout_ms
        self.p95_budget_ms = min(config.fast_lane_deadline_ms, self.timeout_ms)
        self._delay_ms = config.mock_risk_delay_ms
        self._confidence = config.mock_risk_confidence
        self._risk_text = config.mock_risk_text
        self._distance_m = config.mock_risk_distance_m
        self._azimuth_deg = config.mock_risk_azimuth_deg

    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        _ = ctx
        start = time.perf_counter()
        await asyncio.sleep(max(0, self._delay_ms) / 1000.0)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            toolName=self.name,
            toolVersion=self.version,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            latencyMs=latency_ms,
            confidence=self._confidence,
            coordFrame=CoordFrame.WORLD,
            status=ToolStatus.OK,
            payload={
                "riskText": self._risk_text,
                "distanceM": self._distance_m,
                "azimuthDeg": self._azimuth_deg,
                "summary": self._risk_text,
            },
        )
