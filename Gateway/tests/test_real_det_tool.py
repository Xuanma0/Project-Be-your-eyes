from __future__ import annotations

import asyncio

import httpx
import pytest

from byes.config import GatewayConfig
from byes.tools.base import FrameInput, ToolContext
from byes.tools.real_det import RealDetTool


def _config(queue_policy: str = "drop", max_inflight: int = 1) -> GatewayConfig:
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
        slow_lane_deadline_ms=1500,
        fast_q_maxsize=16,
        slow_q_maxsize=16,
        slow_q_drop_threshold=16,
        timeout_rate_threshold=0.35,
        timeout_window_size=20,
        safe_mode_without_ws_client=True,
        ws_disconnect_grace_ms=3000,
        ws_no_client_warn_interval_ms=5000,
        mock_risk_delay_ms=120,
        mock_risk_confidence=0.9,
        mock_risk_distance_m=1.5,
        mock_risk_azimuth_deg=0.0,
        mock_risk_text="Obstacle ahead",
        mock_ocr_delay_ms=200,
        mock_ocr_confidence=0.8,
        mock_ocr_text="Door detected",
        mock_tool_timeout_ms=1200,
        enable_real_det=True,
        real_det_endpoint="http://127.0.0.1:9001/infer",
        real_det_timeout_ms=600,
        real_det_p95_budget_ms=450,
        real_det_max_inflight=max_inflight,
        real_det_queue_policy=queue_policy,
    )


def _frame() -> FrameInput:
    return FrameInput(
        seq=1,
        ts_capture_ms=1000,
        ttl_ms=3000,
        frame_bytes=b"jpg",
        meta={},
    )


def _ctx() -> ToolContext:
    return ToolContext(
        trace_id="0" * 32,
        span_id="0" * 16,
        deadline_ms=2000,
        meta={},
    )


@pytest.mark.asyncio
async def test_real_det_should_skip_when_drop_policy_hits_max_inflight() -> None:
    tool = RealDetTool(_config(queue_policy="drop", max_inflight=1))
    await tool._semaphore.acquire()  # type: ignore[attr-defined]
    try:
        assert tool.should_skip(_frame()) == "max_inflight"
    finally:
        tool._semaphore.release()  # type: ignore[attr-defined]


class _RunnerOk:
    async def infer_bundle(self, request, timeout_ms):  # noqa: ANN001,ANN201
        _ = request
        _ = timeout_ms
        return {
            "detections": [
                {"class": "door", "bbox": [0.1, 0.1, 0.5, 0.8], "confidence": 0.91},
            ]
        }


@pytest.mark.asyncio
async def test_real_det_infer_success_maps_payload() -> None:
    tool = RealDetTool(_config())
    tool._runner = _RunnerOk()  # type: ignore[attr-defined]
    result = await tool.infer(_frame(), _ctx())
    assert result.status.value == "ok"
    assert result.confidence > 0.9
    assert "detections" in result.payload


class _RunnerTimeout:
    async def infer_bundle(self, request, timeout_ms):  # noqa: ANN001,ANN201
        _ = request
        _ = timeout_ms
        raise httpx.ReadTimeout("timeout")


@pytest.mark.asyncio
async def test_real_det_timeout_is_mapped_to_asyncio_timeout() -> None:
    tool = RealDetTool(_config())
    tool._runner = _RunnerTimeout()  # type: ignore[attr-defined]
    with pytest.raises(asyncio.TimeoutError):
        await tool.infer(_frame(), _ctx())
