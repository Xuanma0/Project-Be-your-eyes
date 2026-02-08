from __future__ import annotations

import time

from byes.config import load_config
from byes.degradation import DegradationState
from byes.metrics import GatewayMetrics
from byes.planner import (
    REASON_BUDGET_SKIP,
    REASON_CROSSCHECK,
    REASON_DEGRADED_SKIP,
    REASON_INTENT,
    REASON_POLICY,
    REASON_SAFE_MODE_SKIP,
    REASON_STALE,
    REASON_THROTTLED_SKIP,
    REASON_UNAVAILABLE,
    FrameContext,
    PolicyPlannerV1,
)
from byes.tool_registry import ToolDescriptor
from byes.world_state import WorldState


def _tools() -> list[ToolDescriptor]:
    return [
        ToolDescriptor(
            name="mock_risk",
            version="1.0.0",
            lane="fast",
            capability="risk",
            timeoutMs=300,
            p95BudgetMs=100,
            degradable=False,
        ),
        ToolDescriptor(
            name="mock_ocr",
            version="1.0.0",
            lane="slow",
            capability="ocr",
            timeoutMs=600,
            p95BudgetMs=300,
            degradable=True,
        ),
        ToolDescriptor(
            name="real_det",
            version="1.0.0",
            lane="slow",
            capability="det",
            timeoutMs=700,
            p95BudgetMs=400,
            degradable=True,
        ),
        ToolDescriptor(
            name="real_depth",
            version="1.0.0",
            lane="slow",
            capability="depth",
            timeoutMs=700,
            p95BudgetMs=350,
            degradable=True,
        ),
        ToolDescriptor(
            name="real_ocr",
            version="1.0.0",
            lane="slow",
            capability="ocr",
            timeoutMs=900,
            p95BudgetMs=600,
            degradable=True,
        ),
        ToolDescriptor(
            name="real_vlm",
            version="1.0.0",
            lane="slow",
            capability="vlm",
            timeoutMs=1800,
            p95BudgetMs=1200,
            degradable=True,
        ),
    ]


def _planner_bundle() -> tuple[PolicyPlannerV1, WorldState, GatewayMetrics]:
    config = load_config()
    metrics = GatewayMetrics()
    state = WorldState(config)
    planner = PolicyPlannerV1(config, metrics=metrics, world_state=state)
    return planner, state, metrics


def test_planner_v1_select_reason_labels_stable() -> None:
    planner, state, _metrics = _planner_bundle()
    frame = FrameContext(
        seq=1,
        ts_capture_ms=int(time.time() * 1000),
        ttl_ms=3000,
        meta={"sessionId": "s1", "intent": "none", "performanceMode": "NORMAL"},
    )
    plan = planner.plan(
        frame,
        DegradationState.NORMAL,
        [],
        _tools(),
        health_status="NORMAL",
        world_state=state,
    )
    reasons = {
        str(item.get("reason", ""))
        for item in plan.diagnostics.get("selected_tools", []) + plan.diagnostics.get("skipped_tools", [])
        if isinstance(item, dict)
    }
    allowed = {
        REASON_POLICY,
        REASON_INTENT,
        REASON_CROSSCHECK,
        REASON_STALE,
        REASON_THROTTLED_SKIP,
        REASON_BUDGET_SKIP,
        REASON_SAFE_MODE_SKIP,
        REASON_DEGRADED_SKIP,
        REASON_UNAVAILABLE,
    }
    assert reasons
    assert reasons.issubset(allowed)


def test_planner_v1_throttled_disables_vlm() -> None:
    planner, state, _metrics = _planner_bundle()
    frame = FrameContext(
        seq=3,
        ts_capture_ms=int(time.time() * 1000),
        ttl_ms=3000,
        meta={
            "sessionId": "ask-session",
            "intent": "ask",
            "intentQuestion": "what is in front of me?",
            "performanceMode": "THROTTLED",
        },
    )
    plan = planner.plan(
        frame,
        DegradationState.NORMAL,
        [],
        _tools(),
        health_status="THROTTLED",
        world_state=state,
    )
    selected = [item.tool_name for item in plan.invocations]
    assert "real_vlm" not in selected
    skipped = plan.diagnostics.get("skipped_tools", [])
    assert any(
        isinstance(item, dict)
        and item.get("tool") == "real_vlm"
        and item.get("reason") == REASON_THROTTLED_SKIP
        for item in skipped
    )
    action_hints = plan.diagnostics.get("actionHints", [])
    assert any(isinstance(item, dict) and item.get("actionCategory") == "throttled_ask" for item in action_hints)


def test_planner_v1_crosscheck_forces_det_or_depth() -> None:
    planner, state, _metrics = _planner_bundle()
    now_ms = int(time.time() * 1000)

    cases = [
        ("depth_without_vision", "real_det"),
        ("vision_without_depth", "real_depth"),
    ]
    for conflict_kind, expected_tool in cases:
        state.reset_runtime()
        state.note_crosscheck_conflict(
            session_id="crosscheck",
            kind=conflict_kind,
            now_ms=now_ms,
        )
        frame = FrameContext(
            seq=10,
            ts_capture_ms=now_ms,
            ttl_ms=3000,
            meta={"sessionId": "crosscheck", "intent": "none", "performanceMode": "NORMAL"},
        )
        plan = planner.plan(
            frame,
            DegradationState.NORMAL,
            [],
            _tools(),
            health_status="NORMAL",
            world_state=state,
        )
        assert any(item.tool_name == expected_tool for item in plan.invocations)
        assert any(
            isinstance(item, dict)
            and item.get("tool") == expected_tool
            and item.get("reason") == REASON_CROSSCHECK
            for item in plan.diagnostics.get("selected_tools", [])
        )
