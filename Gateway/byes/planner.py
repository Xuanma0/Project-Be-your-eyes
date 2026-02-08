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
REASON_LATENCY_PRED_EXCEEDS_BUDGET = "latency_pred_exceeds_budget"
REASON_PREEMPT_WINDOW_ACTIVE = "preempt_window_active"
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
    REASON_LATENCY_PRED_EXCEEDS_BUDGET,
    REASON_PREEMPT_WINDOW_ACTIVE,
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
        runtime_stats: object | None = None,
        preempt_window: object | None = None,
    ) -> None:
        self._config = config
        self._metrics = metrics
        self._world_state = world_state
        self._runtime_stats = runtime_stats
        self._preempt_window = preempt_window

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
                critical_until_ms=-1,
                critical_reason=None,
                critical_last_set_ms=-1,
                confirm_confirmed_kinds=[],
                confirm_suppressed_kinds=[],
            )
        )
        confirmed_kinds = {
            str(item).strip().lower()
            for item in snapshot.confirm_confirmed_kinds
            if str(item).strip()
        }
        suppressed_kinds = {
            str(item).strip().lower()
            for item in snapshot.confirm_suppressed_kinds
            if str(item).strip()
        }

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

        preempt_active = self._is_preempt_window_active(now_ms=now_ms, frame=frame)
        if preempt_active:
            for tool in slow_tools:
                _record_skip(self._metrics, skipped_tools, tool.name, REASON_PREEMPT_WINDOW_ACTIVE)
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

        if degradation_state == DegradationState.SAFE_MODE or normalized_health == "SAFE_MODE":
            if _has_confirm_crosscheck_request(frame.meta):
                _metric_call(self._metrics, "inc_confirm_suppressed", "safe_mode")
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
        if forced_kind == "vision_without_depth" and "transparent_obstacle" in suppressed_kinds:
            forced_tool, forced_kind = (None, None)
        if forced_kind == "depth_without_vision" and "dropoff" in suppressed_kinds:
            forced_tool, forced_kind = (None, None)

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
        if "transparent_obstacle" in confirmed_kinds:
            need_det = True
        if "dropoff" in confirmed_kinds:
            need_depth = True

        missing_expected = _missing_expected_tools(
            self._config,
            tools_by_name=tools_by_name,
            active_intent=active_intent,
            need_det=bool(need_det),
            need_depth=bool(need_depth),
            need_ocr=bool(need_ocr),
            need_vlm=bool(need_vlm),
        )
        for tool_name in missing_expected:
            _record_skip(self._metrics, skipped_tools, tool_name, REASON_UNAVAILABLE)
            if tool_name == "real_vlm":
                if working_world_state is None or working_world_state.should_emit_ask_guidance(
                    session_id=session_id,
                    now_ms=now_ms,
                ):
                    action_hints.append(_ask_guidance_hint("unavailable"))

        has_real_vlm = "real_vlm" in tools_by_name

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

            if should_run:
                predicted_latency_ms = self._predict_tool_latency_ms(
                    tool_name=tool_name,
                    performance_mode=performance_mode,
                )
                if predicted_latency_ms is not None:
                    budget_cap_ms = max(
                        1,
                        min(
                            int(self._config.slow_budget_ms),
                            int(slow_budget_remaining_ms),
                        ),
                    )
                    if performance_mode == "THROTTLED":
                        budget_cap_ms = max(1, int(budget_cap_ms * 0.85))
                    if predicted_latency_ms > budget_cap_ms:
                        should_run = False
                        reason = REASON_LATENCY_PRED_EXCEEDS_BUDGET

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

        if confirmed_kinds and normalized_health != "SAFE_MODE":
            should_hint = True
            if working_world_state is not None:
                should_hint = working_world_state.should_emit_ask_guidance(
                    session_id=session_id,
                    now_ms=now_ms,
                )
            if should_hint:
                for kind in sorted(confirmed_kinds):
                    action_hints.append(_confirmed_hazard_hint(kind))

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

    def _predict_tool_latency_ms(self, *, tool_name: str, performance_mode: str) -> float | None:
        if self._runtime_stats is None:
            return None
        quantile = "p50" if str(performance_mode).strip().upper() == "THROTTLED" else "p95"
        predict_fn = getattr(self._runtime_stats, "predict_total_ms", None)
        if not callable(predict_fn):
            return None
        try:
            value = predict_fn(tool_name, quantile=quantile)
        except TypeError:
            try:
                value = predict_fn(tool_name)
            except Exception:  # noqa: BLE001
                return None
        except Exception:  # noqa: BLE001
            return None
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric <= 0:
            return None
        return numeric

    def _is_preempt_window_active(self, *, now_ms: int, frame: FrameContext) -> bool:
        check_fn = getattr(self._preempt_window, "is_active", None)
        if callable(check_fn):
            try:
                return bool(check_fn(int(now_ms)))
            except Exception:  # noqa: BLE001
                pass
        return bool(frame.meta.get("preemptWindowActive", False))


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


def _metric_call(metrics: object | None, method: str, *args: object) -> None:
    if metrics is None:
        return
    fn = getattr(metrics, method, None)
    if callable(fn):
        fn(*args)


def _normalize_reason(reason: str) -> str:
    normalized = str(reason or "").strip().lower().replace("-", "_")
    if normalized in _ALLOWED_REASON_TOKENS:
        return normalized
    return REASON_POLICY


def _session_id_from_meta(meta: dict[str, Any]) -> str:
    session_id = str(meta.get("sessionId", "")).strip()
    return session_id or "default"


def _has_confirm_crosscheck_request(meta: dict[str, Any]) -> bool:
    token = str(meta.get("forceCrosscheckKind", "")).strip().lower()
    return token in {"vision_without_depth", "depth_without_vision"}


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


def _missing_expected_tools(
    config: GatewayConfig,
    *,
    tools_by_name: dict[str, ToolDescriptor],
    active_intent: str,
    need_det: bool,
    need_depth: bool,
    need_ocr: bool,
    need_vlm: bool,
) -> list[str]:
    expected: list[str] = []
    if active_intent in {"ask", "qa"}:
        if need_vlm and _tool_config_enabled(config, "real_vlm"):
            expected.append("real_vlm")
    elif active_intent == "scan_text":
        if need_ocr and _tool_config_enabled(config, "real_ocr"):
            expected.append("real_ocr")
    else:
        if need_det and _tool_config_enabled(config, "real_det"):
            expected.append("real_det")
        if need_depth and _tool_config_enabled(config, "real_depth"):
            expected.append("real_depth")
        if need_ocr and _tool_config_enabled(config, "real_ocr"):
            expected.append("real_ocr")

    missing = [tool_name for tool_name in expected if tool_name not in tools_by_name]
    return sorted(set(missing))


def _tool_config_enabled(config: GatewayConfig, tool_name: str) -> bool:
    normalized = str(tool_name).strip().lower()
    if normalized == "real_det":
        enabled = bool(config.enable_real_det)
    elif normalized == "real_ocr":
        enabled = bool(config.enable_real_ocr)
    elif normalized == "real_depth":
        enabled = bool(config.enable_real_depth)
    elif normalized == "real_vlm":
        enabled = bool(str(config.real_vlm_url).strip())
    else:
        enabled = False
    if not enabled:
        return False

    enabled_csv = str(config.enabled_tools_csv).strip()
    if not enabled_csv:
        return True
    configured = {item.strip().lower() for item in enabled_csv.split(",") if item.strip()}
    return normalized in configured


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


def _confirmed_hazard_hint(kind: str) -> dict[str, Any]:
    normalized_kind = str(kind or "").strip().lower() or "hazard"
    summary = "User confirmed nearby hazard. Stop and scan before moving."
    if normalized_kind == "dropoff":
        summary = "Confirmed drop-off risk. Stop and scan the ground before any movement."
    elif normalized_kind == "transparent_obstacle":
        summary = "Confirmed transparent obstacle. Stop and scan left and right before moving."
    return {
        "type": "action_plan",
        "reason": "confirmed_hazard",
        "actionCategory": "confirm_followup",
        "summary": summary,
        "speech": summary,
        "hud": "Confirmed hazard: stop + scan",
        "mode": "planner_hint",
        "steps": [
            {"action": "stop", "text": "Stop immediately."},
            {"action": "scan", "text": "Scan surroundings carefully."},
            {"action": "confirm", "text": "Confirm route is clear before moving."},
        ],
        "fallback": "scan",
        "confirmKind": normalized_kind,
    }
