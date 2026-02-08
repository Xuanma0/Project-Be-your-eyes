from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from byes.config import GatewayConfig
from byes.degradation import DegradationState
from byes.tool_registry import ToolDescriptor
from byes.tools.base import ToolLane
from byes.world_state import WorldState, WorldStateSnapshot


def _now_ms() -> int:
    return int(time.time() * 1000)


REASON_POLICY = "policy"
REASON_INTENT = "intent"
REASON_CROSSCHECK = "crosscheck"
REASON_STALE = "stale"
REASON_THROTTLED_SKIP = "throttled_skip"
REASON_BUDGET_SKIP = "budget_skip"
REASON_SAFE_MODE_SKIP = "safe_mode_skip"
REASON_DEGRADED_SKIP = "degraded_skip"
REASON_UNAVAILABLE = "unavailable"

_ALLOWED_REASON_TOKENS = {
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


@dataclass(frozen=True)
class FrameContext:
    seq: int
    ts_capture_ms: int
    ttl_ms: int
    meta: dict[str, Any]


@dataclass(frozen=True)
class RecentFrameSummary:
    seq: int
    completed_at_ms: int
    outcome: str
    invoked: int = 0
    timeout: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ToolInvocation:
    tool_name: str
    lane: ToolLane
    timeout_ms: int
    priority: int
    input_variant: str = "full"
    cache_key: str = ""


@dataclass(frozen=True)
class ToolInvocationPlan:
    seq: int
    generated_at_ms: int
    fast_budget_ms: int
    slow_budget_ms: int
    invocations: list[ToolInvocation] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def lane_invocations(self, lane: ToolLane) -> list[ToolInvocation]:
        return [item for item in self.invocations if item.lane == lane]


class PlannerPolicy(Protocol):
    def plan(
        self,
        frame: FrameContext,
        degradation_state: DegradationState,
        recent: list[RecentFrameSummary],
        tools: list[ToolDescriptor],
        *,
        health_status: str | None = None,
        health_reason: str | None = None,
        world_state: WorldState | None = None,
    ) -> ToolInvocationPlan:
        ...


class PolicyPlannerV0:
    """Rule-based planner for v0/v1.9 compatibility."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config

    def plan(
        self,
        frame: FrameContext,
        degradation_state: DegradationState,
        recent: list[RecentFrameSummary],
        tools: list[ToolDescriptor],
        *,
        health_status: str | None = None,
        health_reason: str | None = None,
        world_state: WorldState | None = None,
    ) -> ToolInvocationPlan:
        _ = recent
        _ = health_status
        _ = health_reason
        _ = world_state
        active_intent = str(frame.meta.get("intent", "none")).strip().lower()
        performance_mode = str(frame.meta.get("performanceMode", "NORMAL")).strip().upper()
        invocations: list[ToolInvocation] = []

        fast_tools = [tool for tool in tools if tool.lane == ToolLane.FAST.value]
        slow_tools = [tool for tool in tools if tool.lane == ToolLane.SLOW.value]

        for tool in sorted(fast_tools, key=lambda item: _priority_for(item), reverse=True):
            invocations.append(
                ToolInvocation(
                    tool_name=tool.name,
                    lane=ToolLane.FAST,
                    timeout_ms=min(tool.timeoutMs, self._config.fast_budget_ms),
                    priority=_priority_for(tool),
                    input_variant="full",
                )
            )

        if degradation_state not in {DegradationState.SAFE_MODE, DegradationState.DEGRADED}:
            for tool in sorted(slow_tools, key=lambda item: _priority_for(item), reverse=True):
                if active_intent == "scan_text":
                    if tool.name != "real_ocr":
                        continue
                elif active_intent in {"ask", "qa"}:
                    if tool.name != "real_vlm":
                        continue
                elif tool.name == "real_ocr":
                    continue
                elif tool.name == "real_vlm":
                    continue

                if performance_mode == "THROTTLED":
                    if not _allow_in_throttled_mode(self._config, tool, frame.seq, active_intent):
                        continue

                invocations.append(
                    ToolInvocation(
                        tool_name=tool.name,
                        lane=ToolLane.SLOW,
                        timeout_ms=min(tool.timeoutMs, self._config.slow_budget_ms),
                        priority=_priority_for(tool),
                        input_variant=_input_variant_for(tool),
                    )
                )

        diagnostics = {
            "plannerVersion": "v0",
            "selected_tools": [{"tool": item.tool_name, "reason": REASON_POLICY} for item in invocations],
            "skipped_tools": [],
            "budget_snapshot": {
                "fast_budget_ms": self._config.fast_budget_ms,
                "slow_budget_ms": self._config.slow_budget_ms,
                "slow_budget_remaining_ms": self._config.slow_budget_ms,
                "intent": active_intent,
                "performance_mode": performance_mode,
            },
            "actionHints": [],
        }
        return ToolInvocationPlan(
            seq=frame.seq,
            generated_at_ms=_now_ms(),
            fast_budget_ms=self._config.fast_budget_ms,
            slow_budget_ms=self._config.slow_budget_ms,
            invocations=invocations,
            diagnostics=diagnostics,
        )


class PolicyPlannerV1:
    """v2.0 planner using safety gain + information gain + latency budget heuristics."""

    def __init__(
        self,
        config: GatewayConfig,
        *,
        metrics: object | None = None,
        world_state: WorldState | None = None,
    ) -> None:
        self._config = config
        self._metrics = metrics
        self._world_state = world_state

    def plan(
        self,
        frame: FrameContext,
        degradation_state: DegradationState,
        recent: list[RecentFrameSummary],
        tools: list[ToolDescriptor],
        *,
        health_status: str | None = None,
        health_reason: str | None = None,
        world_state: WorldState | None = None,
    ) -> ToolInvocationPlan:
        _ = recent
        _ = health_reason
        now_ms = _now_ms()
        active_intent = str(frame.meta.get("intent", "none")).strip().lower()
        if active_intent == "qa":
            active_intent = "ask"
        question = str(frame.meta.get("intentQuestion", "")).strip()
        performance_mode = str(frame.meta.get("performanceMode", "NORMAL")).strip().upper()
        session_id = _session_id_from_meta(frame.meta)
        normalized_health = str(health_status or degradation_state.value).strip().upper()
        working_world_state = world_state or self._world_state
        snapshot = (
            working_world_state.snapshot(session_id=session_id, now_ms=now_ms)
            if working_world_state is not None
            else WorldStateSnapshot(
                session_id=session_id,
                last_det=None,
                last_depth_hazards=None,
                last_ocr=None,
                last_vlm_answer=None,
                active_hazards=[],
                crosscheck_kind=None,
                crosscheck_force_tool=None,
                crosscheck_force_expires_ms=-1,
            )
        )

        invocations: list[ToolInvocation] = []
        selected_tools: list[dict[str, str]] = []
        skipped_tools: list[dict[str, str]] = []
        action_hints: list[dict[str, Any]] = []
        slow_budget_remaining_ms = max(1, int(self._config.slow_budget_ms))

        tools_by_name = {item.name: item for item in tools}
        fast_tools = sorted(
            [item for item in tools if item.lane == ToolLane.FAST.value],
            key=lambda item: _priority_for(item),
            reverse=True,
        )
        slow_tools = sorted(
            [item for item in tools if item.lane == ToolLane.SLOW.value],
            key=lambda item: _priority_for(item),
            reverse=True,
        )

        for tool in fast_tools:
            invocation = ToolInvocation(
                tool_name=tool.name,
                lane=ToolLane.FAST,
                timeout_ms=min(tool.timeoutMs, self._config.fast_budget_ms),
                priority=_priority_for(tool),
                input_variant="full",
                cache_key=_cache_key_for(tool),
            )
            invocations.append(invocation)
            _record_select(self._metrics, selected_tools, tool.name, REASON_POLICY)

        if degradation_state == DegradationState.SAFE_MODE or normalized_health == "SAFE_MODE":
            for tool in slow_tools:
                _record_skip(self._metrics, skipped_tools, tool.name, REASON_SAFE_MODE_SKIP)
            return self._build_plan(
                frame=frame,
                invocations=invocations,
                selected_tools=selected_tools,
                skipped_tools=skipped_tools,
                action_hints=action_hints,
                active_intent=active_intent,
                performance_mode=performance_mode,
                health_status=normalized_health,
                slow_budget_remaining_ms=slow_budget_remaining_ms,
            )

        if degradation_state == DegradationState.DEGRADED or normalized_health == "DEGRADED":
            for tool in slow_tools:
                _record_skip(self._metrics, skipped_tools, tool.name, REASON_DEGRADED_SKIP)
            return self._build_plan(
                frame=frame,
                invocations=invocations,
                selected_tools=selected_tools,
                skipped_tools=skipped_tools,
                action_hints=action_hints,
                active_intent=active_intent,
                performance_mode=performance_mode,
                health_status=normalized_health,
                slow_budget_remaining_ms=slow_budget_remaining_ms,
            )

        forced_tool, forced_kind = (None, None)
        if working_world_state is not None:
            forced_tool, forced_kind = working_world_state.peek_forced_tool(session_id=session_id, now_ms=now_ms)

        need_det = True
        need_depth = True
        need_ocr = active_intent == "scan_text"
        need_vlm = active_intent in {"ask", "qa"}
        if working_world_state is not None:
            need_det = working_world_state.need_det(
                session_id=session_id,
                now_ms=now_ms,
                intent=active_intent,
                performance_mode=performance_mode,
            )
            need_depth = working_world_state.need_depth(
                session_id=session_id,
                now_ms=now_ms,
                intent=active_intent,
                performance_mode=performance_mode,
            )
            need_ocr = working_world_state.need_ocr(
                session_id=session_id,
                now_ms=now_ms,
                intent=active_intent,
                performance_mode=performance_mode,
            )
            need_vlm = working_world_state.need_vlm(
                session_id=session_id,
                now_ms=now_ms,
                intent=active_intent,
                performance_mode=performance_mode,
                question=question,
            )

        has_real_vlm = "real_vlm" in tools_by_name
        if active_intent in {"ask", "qa"} and not has_real_vlm:
            _record_skip(self._metrics, skipped_tools, "real_vlm", REASON_UNAVAILABLE)
            if working_world_state is None or working_world_state.should_emit_ask_guidance(
                session_id=session_id,
                now_ms=now_ms,
            ):
                action_hints.append(_ask_guidance_hint("unavailable"))

        for tool in slow_tools:
            reason = REASON_POLICY
            should_run = False
            tool_name = tool.name
            capability = tool.capability.strip().lower()
            estimated_cost_ms = _estimate_tool_cost_ms(tool)

            if forced_tool == tool_name:
                reason = REASON_CROSSCHECK
                should_run = True
            elif active_intent in {"ask", "qa"}:
                if tool_name == "real_vlm":
                    if performance_mode == "THROTTLED":
                        should_run = False
                        reason = REASON_THROTTLED_SKIP
                    elif need_vlm:
                        should_run = True
                        reason = REASON_INTENT
                    else:
                        should_run = False
                        reason = REASON_STALE
                else:
                    should_run = False
                    reason = REASON_INTENT
            elif active_intent == "scan_text":
                if capability == "ocr" and tool_name == "mock_ocr":
                    should_run = True
                    reason = REASON_INTENT
                elif capability == "ocr":
                    should_run = bool(need_ocr)
                    reason = REASON_INTENT if should_run else REASON_STALE
                elif capability in {"depth", "det"}:
                    should_run = False
                    reason = REASON_INTENT
                else:
                    should_run = False
                    reason = REASON_INTENT
            else:
                if capability == "ocr" and tool_name == "mock_ocr":
                    should_run = True
                    reason = REASON_POLICY
                elif capability == "ocr":
                    should_run = bool(need_ocr)
                    reason = REASON_STALE if should_run else REASON_INTENT
                elif capability == "vlm":
                    should_run = False
                    reason = REASON_INTENT
                elif capability == "det":
                    should_run = bool(need_det)
                    reason = REASON_STALE if should_run else REASON_POLICY
                elif capability == "depth":
                    should_run = bool(need_depth)
                    reason = REASON_STALE if should_run else REASON_POLICY
                else:
                    should_run = False
                    reason = REASON_POLICY

            if should_run and performance_mode == "THROTTLED":
                if tool_name == "real_vlm":
                    should_run = False
                    reason = REASON_THROTTLED_SKIP
                elif not _allow_in_throttled_mode(self._config, tool, frame.seq, active_intent):
                    should_run = False
                    reason = REASON_THROTTLED_SKIP

            if should_run and estimated_cost_ms > slow_budget_remaining_ms:
                should_run = False
                reason = REASON_BUDGET_SKIP

            if should_run:
                timeout_ms = min(int(tool.timeoutMs), max(1, slow_budget_remaining_ms))
                invocation = ToolInvocation(
                    tool_name=tool.name,
                    lane=ToolLane.SLOW,
                    timeout_ms=timeout_ms,
                    priority=_priority_for(tool),
                    input_variant=_input_variant_for(tool),
                    cache_key=_cache_key_for(tool),
                )
                invocations.append(invocation)
                slow_budget_remaining_ms = max(0, slow_budget_remaining_ms - estimated_cost_ms)
                _record_select(self._metrics, selected_tools, tool.name, reason)
                if forced_tool == tool_name and working_world_state is not None:
                    working_world_state.consume_forced_tool(
                        session_id=session_id,
                        tool_name=tool_name,
                        now_ms=now_ms,
                    )
            else:
                _record_skip(self._metrics, skipped_tools, tool.name, reason)
                if active_intent in {"ask", "qa"} and tool_name == "real_vlm":
                    if reason in {REASON_THROTTLED_SKIP, REASON_BUDGET_SKIP}:
                        if working_world_state is None or working_world_state.should_emit_ask_guidance(
                            session_id=session_id,
                            now_ms=now_ms,
                        ):
                            action_hints.append(_ask_guidance_hint(reason))

        if forced_tool is not None and all(item.tool_name != forced_tool for item in invocations):
            if forced_tool in tools_by_name:
                _record_skip(self._metrics, skipped_tools, forced_tool, REASON_BUDGET_SKIP)
            else:
                _record_skip(self._metrics, skipped_tools, forced_tool, REASON_UNAVAILABLE)

        if active_intent in {"ask", "qa"} and has_real_vlm:
            has_vlm_selected = any(item.tool_name == "real_vlm" for item in invocations)
            if not has_vlm_selected and not action_hints:
                if working_world_state is None or working_world_state.should_emit_ask_guidance(
                    session_id=session_id,
                    now_ms=now_ms,
                ):
                    action_hints.append(_ask_guidance_hint(REASON_BUDGET_SKIP))

        if forced_kind is not None and invocations:
            for item in selected_tools:
                if item["reason"] == REASON_CROSSCHECK:
                    item["crosscheckKind"] = forced_kind

        return self._build_plan(
            frame=frame,
            invocations=invocations,
            selected_tools=selected_tools,
            skipped_tools=skipped_tools,
            action_hints=action_hints,
            active_intent=active_intent,
            performance_mode=performance_mode,
            health_status=normalized_health,
            slow_budget_remaining_ms=slow_budget_remaining_ms,
        )

    def _build_plan(
        self,
        *,
        frame: FrameContext,
        invocations: list[ToolInvocation],
        selected_tools: list[dict[str, str]],
        skipped_tools: list[dict[str, str]],
        action_hints: list[dict[str, Any]],
        active_intent: str,
        performance_mode: str,
        health_status: str,
        slow_budget_remaining_ms: int,
    ) -> ToolInvocationPlan:
        diagnostics = {
            "plannerVersion": "v1",
            "selected_tools": selected_tools,
            "skipped_tools": skipped_tools,
            "budget_snapshot": {
                "fast_budget_ms": self._config.fast_budget_ms,
                "slow_budget_ms": self._config.slow_budget_ms,
                "slow_budget_remaining_ms": max(0, int(slow_budget_remaining_ms)),
                "intent": active_intent,
                "performance_mode": performance_mode,
                "health_status": health_status,
            },
            "actionHints": action_hints,
        }
        return ToolInvocationPlan(
            seq=frame.seq,
            generated_at_ms=_now_ms(),
            fast_budget_ms=self._config.fast_budget_ms,
            slow_budget_ms=self._config.slow_budget_ms,
            invocations=invocations,
            diagnostics=diagnostics,
        )


def _record_select(metrics: object | None, bucket: list[dict[str, str]], tool: str, reason: str) -> None:
    normalized_reason = _normalize_reason(reason)
    bucket.append({"tool": tool, "reason": normalized_reason})
    if metrics is None:
        return
    fn = getattr(metrics, "inc_planner_select", None)
    if callable(fn):
        fn(tool, normalized_reason)


def _record_skip(metrics: object | None, bucket: list[dict[str, str]], tool: str, reason: str) -> None:
    normalized_reason = _normalize_reason(reason)
    bucket.append({"tool": tool, "reason": normalized_reason})
    if metrics is None:
        return
    fn = getattr(metrics, "inc_planner_skip", None)
    if callable(fn):
        fn(tool, normalized_reason)


def _normalize_reason(reason: str) -> str:
    normalized = str(reason or "").strip().lower().replace("-", "_")
    if normalized in _ALLOWED_REASON_TOKENS:
        return normalized
    return REASON_POLICY


def _session_id_from_meta(meta: dict[str, Any]) -> str:
    session_id = str(meta.get("sessionId", "")).strip()
    return session_id or "default"


def _priority_for(tool: ToolDescriptor) -> int:
    if tool.name == "mock_ocr":
        return 360
    capability = tool.capability.lower()
    if capability == "risk":
        return 1000
    if capability == "depth":
        return 340
    if capability == "det":
        return 320
    if capability == "ocr":
        return 260
    if capability == "vlm":
        return 230
    return 100


def _input_variant_for(tool: ToolDescriptor) -> str:
    capability = tool.capability.lower()
    if tool.name == "real_det" or capability == "det":
        return "det"
    if tool.name == "real_ocr" or capability == "ocr":
        return "ocr"
    if tool.name == "real_depth" or capability == "depth":
        return "depth"
    if tool.name == "real_vlm" or capability == "vlm":
        return "full"
    return "full"


def _cache_key_for(tool: ToolDescriptor) -> str:
    if tool.name in {"real_det", "real_ocr", "real_depth", "real_vlm"}:
        return "fingerprint"
    return ""


def _estimate_tool_cost_ms(tool: ToolDescriptor) -> int:
    if tool.name == "mock_ocr":
        return max(20, min(200, int(tool.timeoutMs)))
    if tool.name == "mock_risk":
        return max(20, min(120, int(tool.timeoutMs)))
    return max(20, min(int(tool.p95BudgetMs), int(tool.timeoutMs)))


def _allow_in_throttled_mode(config: GatewayConfig, tool: ToolDescriptor, seq: int, active_intent: str) -> bool:
    name = tool.name.strip().lower()
    if name == "real_vlm":
        return False
    if name == "real_ocr":
        if active_intent == "scan_text":
            return True
        every_n = max(1, int(config.throttled_ocr_every_n_frames))
        return seq % every_n == 0
    if name == "real_det":
        every_n = max(1, int(config.throttled_det_every_n_frames))
        return seq % every_n == 0
    if name == "real_depth":
        every_n = max(1, int(config.throttled_depth_every_n_frames))
        return seq % every_n == 0
    if name == "mock_ocr":
        every_n = max(1, int(config.throttled_ocr_every_n_frames))
        return seq % every_n == 0
    return True


def _ask_guidance_hint(reason: str) -> dict[str, Any]:
    normalized = _normalize_reason(reason)
    summary = "Ask mode delayed by system load. Try scan_text or a shorter question."
    if normalized == REASON_UNAVAILABLE:
        summary = "Ask mode unavailable. Use scan_text for immediate reading."
    elif normalized == REASON_BUDGET_SKIP:
        summary = "Ask mode delayed by latency budget. Try scan_text first."
    return {
        "type": "action_plan",
        "reason": normalized,
        "actionCategory": "throttled_ask",
        "summary": summary,
        "speech": summary,
        "hud": "Ask delayed: use scan_text",
        "mode": "planner_hint",
        "steps": [
            {"action": "stop", "text": "Stop for safety."},
            {"action": "scan", "text": "Scan environment or text."},
            {"action": "confirm", "text": "Confirm before moving."},
        ],
        "fallback": "scan",
    }
