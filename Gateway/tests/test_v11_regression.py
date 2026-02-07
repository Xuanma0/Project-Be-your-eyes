from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi import FastAPI

from byes.config import GatewayConfig
from byes.degradation import DegradationManager, DegradationState
from byes.faults import FaultManager
from byes.fusion import FusionEngine
from byes.safety import SafetyKernel
from byes.scheduler import Scheduler
from byes.schema import EventType, ToolResult
from byes.tool_registry import ToolRegistry
from byes.tools import MockOcrTool, MockRiskTool
from byes.tools.base import FrameInput, ToolLane
from main import GatewayApp


class CaptureConnection:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def broadcast_json(self, obj: dict[str, Any]) -> None:
        self.messages.append(obj)


def make_config() -> GatewayConfig:
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
        timeout_rate_threshold=0.25,
        timeout_window_size=4,
        safe_mode_without_ws_client=True,
        ws_disconnect_grace_ms=3000,
        ws_no_client_warn_interval_ms=1000,
        mock_risk_delay_ms=60,
        mock_risk_confidence=0.9,
        mock_risk_distance_m=1.5,
        mock_risk_azimuth_deg=0.0,
        mock_risk_text="Obstacle ahead",
        mock_ocr_delay_ms=80,
        mock_ocr_confidence=0.8,
        mock_ocr_text="Door detected",
        mock_tool_timeout_ms=300,
    )


def test_ws_no_client_should_not_safemode() -> None:
    now_holder = {"value": 0}

    def now_ms() -> int:
        return now_holder["value"]

    manager = DegradationManager(make_config(), now_ms_fn=now_ms)
    manager.set_ws_client_count(0)

    now_holder["value"] += 10_000
    manager.tick()

    assert manager.had_client_ever_connected is False
    assert manager.state != DegradationState.SAFE_MODE
    alerts = manager.consume_alerts()
    assert any(alert.status == "gateway_waiting_client" for alert in alerts)


@pytest.mark.asyncio
async def test_fault_timeout_triggers_degrade() -> None:
    config = make_config()
    # Fault timeout should drive degradation through timeout-rate signal only.
    config = GatewayConfig(
        **{**config.__dict__, "safe_mode_without_ws_client": False}
    )

    registry = ToolRegistry()
    registry.register(MockRiskTool(config))
    registry.register(MockOcrTool(config))

    degradation = DegradationManager(config)
    faults = FaultManager()
    fusion = FusionEngine(config)
    safety = SafetyKernel(config, degradation)
    emitted_types: list[EventType] = []

    async def on_lane_results(frame: FrameInput, lane: ToolLane, results: list[ToolResult]) -> None:
        fused = fusion.fuse_lane(frame, lane, results, trace_id="0" * 32, span_id="0" * 16)
        decision = safety.adjudicate(fused.events, now_ms=int(time.time() * 1000))
        for event in decision.events:
            if not event.is_expired():
                emitted_types.append(event.type)

    scheduler = Scheduler(
        config=config,
        registry=registry,
        on_lane_results=on_lane_results,
        degradation_manager=degradation,
        fault_manager=faults,
    )

    await scheduler.start()
    await faults.set_fault(tool="mock_ocr", mode="timeout", value=True, duration_ms=None)

    for _ in range(5):
        await scheduler.submit_frame(
            frame_bytes=b"frame",
            meta={"ttlMs": 3000},
            trace_id="a" * 32,
            span_id="b" * 16,
        )
        await asyncio.sleep(0.12)

    await asyncio.sleep(0.4)
    await scheduler.stop()
    await faults.shutdown()

    assert degradation.state in {DegradationState.DEGRADED, DegradationState.SAFE_MODE}
    assert EventType.RISK in emitted_types
    assert all(event_type in {EventType.RISK, EventType.HEALTH} for event_type in emitted_types)


@pytest.mark.asyncio
async def test_ttl_drop_never_emit() -> None:
    gateway_app = GatewayApp(FastAPI())
    capture = CaptureConnection()
    gateway_app.connections = capture  # type: ignore[assignment]

    await gateway_app.startup()
    if gateway_app._degrade_watchdog_task is not None:
        gateway_app._degrade_watchdog_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await gateway_app._degrade_watchdog_task
        gateway_app._degrade_watchdog_task = None

    expired_ts = int(time.time() * 1000) - 5000
    await gateway_app.scheduler.submit_frame(
        frame_bytes=b"expired",
        meta={"tsCaptureMs": expired_ts, "ttlMs": 10},
        trace_id="c" * 32,
        span_id="d" * 16,
    )

    await asyncio.sleep(0.3)
    await gateway_app.shutdown()

    assert all(msg.get("type") not in {"risk", "perception"} for msg in capture.messages)
