from __future__ import annotations

import time

from byes.config import GatewayConfig
from byes.safety import SafetyKernel
from byes.schema import CoordFrame, EventType, ToolResult, ToolStatus
from byes.fusion import FusionEngine
from byes.tools.base import FrameInput, ToolLane


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
        enable_real_det=True,
        enable_real_depth=True,
        crosscheck_cooldown_ms=0,
    )


def _frame() -> FrameInput:
    now = int(time.time() * 1000)
    return FrameInput(
        seq=1,
        ts_capture_ms=now,
        ttl_ms=3000,
        frame_bytes=b"img",
        meta={"sessionId": "test-session"},
    )


def _det_result(cls: str, conf: float = 0.9) -> ToolResult:
    return ToolResult(
        toolName="real_det",
        toolVersion="0.1",
        seq=1,
        tsCaptureMs=_frame().ts_capture_ms,
        latencyMs=20,
        confidence=conf,
        coordFrame=CoordFrame.WORLD,
        status=ToolStatus.OK,
        payload={
            "detections": [{"class": cls, "bbox": [0.2, 0.2, 0.6, 0.8], "confidence": conf}],
            "summary": f"Detected {cls}",
        },
    )


def _depth_result(hazards: list[dict[str, float | str]]) -> ToolResult:
    confidence = max((float(item.get("confidence", 0.0)) for item in hazards), default=0.0)
    return ToolResult(
        toolName="real_depth",
        toolVersion="0.1",
        seq=1,
        tsCaptureMs=_frame().ts_capture_ms,
        latencyMs=30,
        confidence=confidence,
        coordFrame=CoordFrame.WORLD,
        status=ToolStatus.OK,
        payload={"hazards": hazards, "summary": "depth"},
    )


def _find_event(events: list, event_type: EventType):
    for event in events:
        if event.type == event_type:
            return event
    return None


def test_crosscheck_transparent_obstacle_confirm() -> None:
    fusion = FusionEngine(_config())
    frame = _frame()
    det = _det_result("glass door", conf=0.88)
    depth = _depth_result([])

    output = fusion.fuse_lane(
        frame=frame,
        lane=ToolLane.SLOW,
        results=[det, depth],
        trace_id="1" * 32,
        span_id="2" * 16,
        health_status="NORMAL",
    )

    risk = _find_event(output.events, EventType.RISK)
    action_plan = _find_event(output.events, EventType.ACTION_PLAN)
    assert risk is not None
    assert action_plan is not None
    assert risk.payload.get("crosscheckKind") == "vision_without_depth"
    assert bool(risk.payload.get("activeConfirm", False)) is True
    assert "confirm" in str(risk.payload.get("summary", "")).lower()
    plan = action_plan.payload.get("plan", {})
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    actions = [str(step.get("action", "")) for step in steps if isinstance(step, dict)]
    assert "stop" in actions
    assert "scan" in actions
    assert action_plan.payload.get("reason") == "crosscheck_patch"


def test_crosscheck_dropoff_confirm() -> None:
    fusion = FusionEngine(_config())
    frame = _frame()
    det = _det_result("poster", conf=0.2)
    depth = _depth_result([{"distanceM": 1.0, "azimuthDeg": 2.0, "confidence": 0.91, "kind": "dropoff"}])

    output = fusion.fuse_lane(
        frame=frame,
        lane=ToolLane.SLOW,
        results=[det, depth],
        trace_id="1" * 32,
        span_id="2" * 16,
        health_status="DEGRADED",
    )

    risk = _find_event(output.events, EventType.RISK)
    action_plan = _find_event(output.events, EventType.ACTION_PLAN)
    assert risk is not None
    assert action_plan is not None
    assert risk.payload.get("crosscheckKind") == "depth_without_vision"
    assert bool(risk.payload.get("activeConfirm", False)) is True
    assert "scan" in str(risk.payload.get("summary", "")).lower()
    plan = action_plan.payload.get("plan", {})
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    actions = [str(step.get("action", "")) for step in steps if isinstance(step, dict)]
    assert "stop" in actions
    assert "scan" in actions


def test_crosscheck_safemode_blocks_actionplan() -> None:
    cfg = _config()
    fusion = FusionEngine(cfg)
    safety = SafetyKernel(cfg, _SafeModeStub())
    frame = _frame()
    det = _det_result("glass door", conf=0.9)
    depth = _depth_result([])

    output = fusion.fuse_lane(
        frame=frame,
        lane=ToolLane.SLOW,
        results=[det, depth],
        trace_id="1" * 32,
        span_id="2" * 16,
        health_status="SAFE_MODE",
    )
    decision = safety.adjudicate(output.events, now_ms=int(time.time() * 1000))

    assert any(event.type == EventType.RISK for event in decision.events)
    assert all(event.type in {EventType.RISK, EventType.HEALTH} for event in decision.events)
    assert all(event.type != EventType.ACTION_PLAN for event in decision.events)
