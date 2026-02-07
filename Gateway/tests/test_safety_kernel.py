from __future__ import annotations

import time

from byes.config import GatewayConfig
from byes.safety import SafetyKernel
from byes.schema import CoordFrame, EventEnvelope, EventType


class SafeModeStub:
    def __init__(self, safe_mode: bool) -> None:
        self._safe_mode = safe_mode

    def is_safe_mode(self) -> bool:
        return self._safe_mode


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
        slow_lane_deadline_ms=1500,
        fast_q_maxsize=16,
        slow_q_maxsize=16,
        slow_q_drop_threshold=16,
        timeout_rate_threshold=0.35,
        timeout_window_size=20,
        safe_mode_without_ws_client=True,
        mock_risk_delay_ms=120,
        mock_risk_confidence=0.9,
        mock_risk_distance_m=1.5,
        mock_risk_azimuth_deg=0.0,
        mock_risk_text="Obstacle ahead",
        mock_ocr_delay_ms=180,
        mock_ocr_confidence=0.8,
        mock_ocr_text="Door detected",
        mock_tool_timeout_ms=1200,
    )


def _event(event_type: EventType, confidence: float, priority: int, payload: dict[str, object]) -> EventEnvelope:
    now = int(time.time() * 1000)
    return EventEnvelope(
        type=event_type,
        traceId="1" * 32,
        spanId="2" * 16,
        seq=1,
        tsCaptureMs=now,
        ttlMs=3000,
        coordFrame=CoordFrame.WORLD,
        confidence=confidence,
        priority=priority,
        source="test@1.0",
        payload=payload,
    )


def test_risk_preempts_other_events() -> None:
    kernel = SafetyKernel(make_config())
    now = int(time.time() * 1000)

    risk = _event(EventType.RISK, 0.9, 100, {"riskText": "Obstacle ahead"})
    perception = _event(EventType.PERCEPTION, 0.9, 10, {"summary": "Door detected"})

    decision = kernel.adjudicate([perception, risk], now_ms=now)

    assert len(decision.events) == 1
    assert decision.events[0].type == EventType.RISK


def test_low_confidence_navigation_is_forced_to_stop() -> None:
    kernel = SafetyKernel(make_config())
    now = int(time.time() * 1000)

    navigation = _event(EventType.NAVIGATION, 0.2, 20, {"action": "move", "text": "go forward"})
    decision = kernel.adjudicate([navigation], now_ms=now)

    assert len(decision.events) == 1
    payload = decision.events[0].payload
    assert payload["action"] == "stop"
    assert payload["fallback"] == "scan"


def test_safe_mode_allows_only_risk_and_health() -> None:
    kernel = SafetyKernel(make_config(), SafeModeStub(safe_mode=True))
    now = int(time.time() * 1000)

    perception = _event(EventType.PERCEPTION, 0.8, 10, {"summary": "Door"})
    health = _event(EventType.HEALTH, 1.0, 90, {"status": "gateway_safe_mode"})

    decision = kernel.adjudicate([perception, health], now_ms=now)

    assert len(decision.events) == 1
    assert decision.events[0].type == EventType.HEALTH
