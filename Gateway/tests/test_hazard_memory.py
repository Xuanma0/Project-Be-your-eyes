from __future__ import annotations

from collections import Counter

from byes.config import GatewayConfig
from byes.hazard_memory import HazardMemory
from byes.schema import CoordFrame, EventEnvelope, EventType


class _MetricsStub:
    def __init__(self) -> None:
        self.emit = Counter()
        self.suppressed = Counter()
        self.persist = Counter()
        self.last_active = -1

    def inc_hazard_emit(self, kind: str) -> None:
        self.emit[kind] += 1

    def inc_hazard_suppressed(self, reason: str) -> None:
        self.suppressed[reason] += 1

    def inc_hazard_persist(self, kind: str) -> None:
        self.persist[kind] += 1

    def set_hazard_active(self, value: int) -> None:
        self.last_active = int(value)


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
        slow_lane_deadline_ms=1200,
        fast_q_maxsize=32,
        slow_q_maxsize=32,
        slow_q_drop_threshold=32,
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
        mock_tool_timeout_ms=1200,
        hazard_memory_grace_ms=1200,
        hazard_memory_emit_cooldown_ms=4000,
        hazard_memory_critical_dist_m=1.0,
        hazard_memory_max_active=64,
        hazard_memory_decay_ms=8000,
    )


def _risk_event(
    *,
    ts_capture_ms: int,
    summary: str = "Obstacle ahead",
    risk_text: str = "Obstacle ahead",
    distance_m: float = 1.4,
    azimuth_deg: float = 0.0,
    hazard_kind: str | None = None,
) -> EventEnvelope:
    payload: dict[str, object] = {
        "riskText": risk_text,
        "summary": summary,
        "distanceM": distance_m,
        "azimuthDeg": azimuth_deg,
    }
    if hazard_kind is not None:
        payload["hazardKind"] = hazard_kind
    return EventEnvelope(
        type=EventType.RISK,
        traceId="1" * 32,
        spanId="2" * 16,
        seq=1,
        tsCaptureMs=ts_capture_ms,
        ttlMs=3000,
        coordFrame=CoordFrame.WORLD,
        confidence=0.9,
        priority=100,
        source="mock_risk@v1",
        payload=payload,
    )


def test_dedup_cooldown_suppresses() -> None:
    metrics = _MetricsStub()
    memory = HazardMemory(_config(), metrics=metrics)
    now = 1_000_000

    first = memory.update_and_filter(
        session_id="session-a",
        risks=[_risk_event(ts_capture_ms=now), _risk_event(ts_capture_ms=now)],
        now_ms=now,
    )
    assert len(first) == 1

    for idx in range(1, 5):
        emitted = memory.update_and_filter(
            session_id="session-a",
            risks=[_risk_event(ts_capture_ms=now + idx * 100)],
            now_ms=now + idx * 100,
        )
        assert emitted == []

    assert metrics.emit["obstacle"] == 1
    assert metrics.suppressed["duplicate"] >= 1
    assert metrics.suppressed["cooldown"] >= 1


def test_grace_persists_on_miss() -> None:
    metrics = _MetricsStub()
    memory = HazardMemory(_config(), metrics=metrics)
    now = 2_000_000
    emitted = memory.update_and_filter(
        session_id="session-b",
        risks=[_risk_event(ts_capture_ms=now, summary="Unknown obstacle")],
        now_ms=now,
    )
    assert len(emitted) == 1

    _ = memory.update_and_filter(
        session_id="session-b",
        risks=[],
        now_ms=now + 300,
    )

    assert metrics.last_active > 0
    assert sum(metrics.persist.values()) > 0


def test_critical_bypass_emits() -> None:
    metrics = _MetricsStub()
    memory = HazardMemory(_config(), metrics=metrics)
    now = 3_000_000
    first = memory.update_and_filter(
        session_id="session-c",
        risks=[_risk_event(ts_capture_ms=now, summary="Drop ahead", hazard_kind="dropoff", distance_m=0.8)],
        now_ms=now,
    )
    second = memory.update_and_filter(
        session_id="session-c",
        risks=[_risk_event(ts_capture_ms=now + 100, summary="Drop ahead", hazard_kind="dropoff", distance_m=0.8)],
        now_ms=now + 100,
    )

    assert len(first) == 1
    assert len(second) == 1
    assert metrics.emit["dropoff"] >= 2


def test_reset_clears_memory() -> None:
    metrics = _MetricsStub()
    memory = HazardMemory(_config(), metrics=metrics)
    now = 4_000_000
    _ = memory.update_and_filter(
        session_id="session-d",
        risks=[_risk_event(ts_capture_ms=now)],
        now_ms=now,
    )
    assert metrics.last_active > 0

    memory.reset_runtime()
    assert metrics.last_active == 0
