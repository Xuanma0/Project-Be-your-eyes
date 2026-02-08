from __future__ import annotations

import time

from byes.config import GatewayConfig
from byes.safety import SafetyKernel
from byes.schema import CoordFrame, EventEnvelope, EventType


class _SafeModeStub:
    def is_safe_mode(self) -> bool:
        return True

    def is_degraded(self) -> bool:
        return True


def _config() -> GatewayConfig:
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
        mock_ocr_delay_ms=180,
        mock_ocr_confidence=0.8,
        mock_ocr_text="Door detected",
        mock_tool_timeout_ms=1200,
        planner_recent_window=8,
        fast_budget_ms=500,
        slow_budget_ms=1200,
    )


def _event(event_type: EventType, priority: int, payload: dict[str, object]) -> EventEnvelope:
    now = int(time.time() * 1000)
    return EventEnvelope(
        type=event_type,
        traceId="1" * 32,
        spanId="2" * 16,
        seq=1,
        tsCaptureMs=now,
        ttlMs=3000,
        coordFrame=CoordFrame.WORLD,
        confidence=0.9,
        priority=priority,
        source="test@1.0",
        payload=payload,
    )


def test_actionplan_is_blocked_in_safe_mode() -> None:
    kernel = SafetyKernel(_config(), _SafeModeStub())
    now = int(time.time() * 1000)

    action_plan = _event(EventType.ACTION_PLAN, 20, {"summary": "move ahead", "plan": {"steps": [{"action": "move"}]}})
    perception = _event(EventType.PERCEPTION, 10, {"summary": "Door detected"})
    health = _event(EventType.HEALTH, 90, {"status": "gateway_safe_mode"})

    decision = kernel.adjudicate([action_plan, perception, health], now_ms=now)

    assert len(decision.events) == 1
    assert decision.events[0].type == EventType.HEALTH
