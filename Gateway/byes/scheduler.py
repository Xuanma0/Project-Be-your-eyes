from __future__ import annotations

import asyncio
import contextlib
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from byes.config import GatewayConfig
from byes.degradation import DegradationState
from byes.faults import FaultManager
from byes.frame_gate import FrameContext as GateFrameContext
from byes.frame_gate import FrameGate
from byes.frame_tracker import FrameTracker
from byes.observability import Observability, TraceInfo
from byes.planner import FrameContext, PlannerPolicy, RecentFrameSummary, ToolInvocationPlan
from byes.preprocess import FrameArtifacts, FramePreprocessor
from byes.schema import ToolResult, ToolStatus
from byes.tool_registry import ToolRegistry
from byes.tool_cache import ToolCache
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane
from byes.world_state import WorldState

if TYPE_CHECKING:
    from byes.mode_state import ModeProfile

OnLaneResults = Callable[[FrameInput, ToolLane, list[ToolResult]], Awaitable[None]]
OnFrameTerminal = Callable[[FrameInput, str], None]


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class _QueuedTask:
    frame: FrameInput
    trace_id: str
    span_id: str
    enqueued_at_ms_by_lane: dict[str, int] = field(default_factory=dict)


class Scheduler:
    PREEMPT_REASON = "preempted_by_critical_risk"
    PREEMPT_METRIC_REASON = "critical_risk"

    def __init__(
        self,
        config: GatewayConfig,
        registry: ToolRegistry,
        on_lane_results: OnLaneResults,
        metrics: Any | None = None,
        degradation_manager: Any | None = None,
        observability: Observability | None = None,
        fault_manager: FaultManager | None = None,
        on_frame_terminal: OnFrameTerminal | None = None,
        planner: PlannerPolicy | None = None,
        frame_gate: FrameGate | None = None,
        tool_cache: ToolCache | None = None,
        frame_tracker: FrameTracker | None = None,
        preprocessor: FramePreprocessor | None = None,
        world_state: WorldState | None = None,
        runtime_stats: object | None = None,
        preempt_window: object | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._on_lane_results = on_lane_results
        self._metrics = metrics
        self._degradation = degradation_manager
        self._observability = observability
        self._faults = fault_manager
        self._on_frame_terminal = on_frame_terminal
        self._planner = planner
        self._frame_gate = frame_gate or FrameGate(config)
        self._tool_cache = tool_cache or ToolCache(config.tool_cache_max_entries)
        self._frame_tracker = frame_tracker
        self._preprocessor = preprocessor
        self._world_state = world_state
        self._runtime_stats = runtime_stats
        self._preempt_window = preempt_window

        self._seq = 0
        self._latest_seq = 0
        self._lock = asyncio.Lock()
        self._running = False

        self._fast_q: asyncio.Queue[_QueuedTask] = asyncio.Queue(maxsize=config.fast_q_maxsize)
        self._slow_q: asyncio.Queue[_QueuedTask] = asyncio.Queue(maxsize=config.slow_q_maxsize)
        self._workers: list[asyncio.Task[None]] = []
        self._active_by_seq: dict[int, set[asyncio.Task[ToolResult]]] = defaultdict(set)
        self._task_lane: dict[asyncio.Task[ToolResult], ToolLane] = {}
        self._frame_by_seq: dict[int, FrameInput] = {}
        self._plan_by_seq: dict[int, ToolInvocationPlan] = {}
        self._recent_summaries: deque[RecentFrameSummary] = deque(maxlen=max(1, config.planner_recent_window))
        self._frame_tool_stats: dict[int, dict[str, int]] = {}

    async def start(self) -> None:
        if self._running:
            return

        # Recreate queues on each startup so scheduler can restart safely across loops/tests.
        self._fast_q = asyncio.Queue(maxsize=self._config.fast_q_maxsize)
        self._slow_q = asyncio.Queue(maxsize=self._config.slow_q_maxsize)
        self._active_by_seq.clear()
        self._task_lane.clear()
        self._frame_by_seq.clear()
        self._plan_by_seq.clear()
        self._frame_tool_stats.clear()
        self._recent_summaries.clear()
        self._frame_gate.reset_runtime()
        self._tool_cache.reset_runtime()

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker_loop(ToolLane.FAST), name="byes-fast-worker"),
            asyncio.create_task(self._worker_loop(ToolLane.SLOW), name="byes-slow-worker"),
        ]
        self._set_queue_depth_metrics()
        self._set_preempt_window_gauge()

    def reset_runtime(self) -> None:
        for tasks in self._active_by_seq.values():
            for task in tasks:
                if not task.done():
                    task.cancel()
        self._active_by_seq.clear()
        self._task_lane.clear()
        self._frame_by_seq.clear()
        self._plan_by_seq.clear()
        self._frame_tool_stats.clear()
        self._recent_summaries.clear()
        self._frame_gate.reset_runtime()
        self._tool_cache.reset_runtime()
        self._drain_queue(self._fast_q)
        self._drain_queue(self._slow_q)
        self._set_queue_depth_metrics()
        self._set_preempt_window_gauge()

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        for worker in self._workers:
            worker.cancel()

        for tasks in self._active_by_seq.values():
            for task in tasks:
                task.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._active_by_seq.clear()
        self._task_lane.clear()
        self._frame_by_seq.clear()
        self._plan_by_seq.clear()
        self._frame_tool_stats.clear()
        self._set_queue_depth_metrics()
        self._set_preempt_window_gauge()

    async def submit_frame(
        self,
        frame_bytes: bytes,
        meta: dict[str, Any] | None,
        trace_id: str,
        span_id: str,
    ) -> int:
        if not self._running:
            raise RuntimeError("scheduler is not running")

        payload = dict(meta or {})
        now = _now_ms()
        ts_capture_ms = int(payload.get("tsCaptureMs", now))
        ttl_ms = int(payload.get("ttlMs", self._config.default_ttl_ms))
        ttl_ms = ttl_ms if ttl_ms > 0 else self._config.default_ttl_ms
        preserve_old = bool(payload.get("preserveOld", False))

        async with self._lock:
            self._seq += 1
            seq = self._seq
            self._latest_seq = max(self._latest_seq, seq)
            if not preserve_old:
                self._cancel_older_active(seq)

        frame = FrameInput(
            seq=seq,
            ts_capture_ms=ts_capture_ms,
            ttl_ms=ttl_ms,
            frame_bytes=frame_bytes,
            meta=payload,
        )
        frame.meta["_fast_risk_critical"] = False
        self._frame_by_seq[seq] = frame
        self._frame_tool_stats[seq] = {"invoked": 0, "timeout": 0, "skipped": 0}
        self._plan_by_seq[seq] = self._build_plan(frame)
        queued = _QueuedTask(
            frame=frame,
            trace_id=trace_id,
            span_id=span_id,
            enqueued_at_ms_by_lane={ToolLane.FAST.value: _now_ms()},
        )

        await self._fast_q.put(queued)
        self._set_queue_depth_metrics()
        frame.meta["_slow_enqueued"] = False
        self._set_queue_depth_metrics()

        return seq

    async def _worker_loop(self, lane: ToolLane) -> None:
        queue = self._fast_q if lane == ToolLane.FAST else self._slow_q
        while True:
            self._set_preempt_window_gauge()
            queued = await queue.get()
            self._set_queue_depth_metrics()
            try:
                if self._should_skip_frame(queued.frame):
                    self._complete_frame(queued.frame, "canceled")
                    continue

                if self._is_expired(queued.frame.ts_capture_ms, queued.frame.ttl_ms, _now_ms()):
                    self._metric_call("inc_deadline_miss", lane.value)
                    self._complete_frame(queued.frame, "ttl_drop")
                    continue

                results = await self._run_tools_for_lane(queued, lane)
                if results:
                    await self._on_lane_results(queued.frame, lane, results)
                    if lane == ToolLane.FAST:
                        now_ms = _now_ms()
                        emitted_critical_risk = bool(queued.frame.meta.get("_fast_risk_critical", False))
                        if emitted_critical_risk or self._has_critical_risk_result(results):
                            self._enter_preempt_window(now_ms)
                            self._record_critical_preempt_skip(queued.frame)
                            queued.frame.meta["_slow_enqueued"] = False
                        elif self._is_preempt_window_active(now_ms):
                            self._record_preempt_window_skip(queued.frame)
                            queued.frame.meta["_slow_enqueued"] = False
                        else:
                            queued.frame.meta["_slow_enqueued"] = self._enqueue_slow_after_fast(queued)
                        self._record_recent_summary(queued.frame.seq, "ok")
                        if not bool(queued.frame.meta.get("_slow_enqueued", False)):
                            self._discard_frame_runtime(queued.frame.seq)
                    elif lane == ToolLane.SLOW:
                        self._discard_frame_runtime(queued.frame.seq)
                elif lane == ToolLane.FAST:
                    safe_mode = bool(self._safe_call(self._degradation, "is_safe_mode", default=False))
                    self._complete_frame(queued.frame, "safemode_suppressed" if safe_mode else "error")
                elif lane == ToolLane.SLOW:
                    self._discard_frame_runtime(queued.frame.seq)
            finally:
                queue.task_done()
                self._set_queue_depth_metrics()

    async def _run_tools_for_lane(self, queued: _QueuedTask, lane: ToolLane) -> list[ToolResult]:
        degraded = bool(self._safe_call(self._degradation, "is_degraded", default=False))
        safe_mode = bool(self._safe_call(self._degradation, "is_safe_mode", default=False))
        now_ms = _now_ms()
        fingerprint = str(queued.frame.meta.get("fingerprint", ""))
        intent = str(queued.frame.meta.get("intent", "none"))

        all_lane_tools = self._registry.all_lane_tools(lane)
        all_lane_tool_names = {tool.name for tool in all_lane_tools}
        planner_skip_reasons = self._planner_skip_reasons(self._plan_by_seq.get(queued.frame.seq))
        available_tools = self._registry.lane_tools(
            lane=lane,
            degraded=degraded,
            safe_mode=safe_mode,
        )
        available_map = {tool.name: tool for tool in available_tools}

        raw_plan = self._plan_by_seq.get(queued.frame.seq)
        use_plan = False
        if raw_plan is not None:
            if raw_plan.invocations:
                use_plan = True
            elif isinstance(raw_plan.diagnostics, dict):
                skipped_diag = raw_plan.diagnostics.get("skipped_tools")
                use_plan = isinstance(skipped_diag, list) and len(skipped_diag) > 0

        plan = raw_plan if use_plan else None
        self._emit_planner_unavailable_skips(queued.frame, plan, all_lane_tool_names)
        planned = plan.lane_invocations(lane) if plan is not None else []
        tools: list[BaseTool] = []
        planned_by_name: dict[str, Any] = {}
        if plan is not None:
            ordered_plan = sorted(planned, key=lambda item: item.priority, reverse=True)
            for invocation in ordered_plan:
                tool = available_map.get(invocation.tool_name)
                if tool is None:
                    continue
                tools.append(tool)
                planned_by_name[tool.name] = invocation
        else:
            tools = list(available_tools)

        selected_names = {tool.name for tool in tools}
        for tool in all_lane_tools:
            if tool.name in selected_names:
                continue
            reason_from_plan = planner_skip_reasons.get(tool.name)
            if reason_from_plan:
                reason = reason_from_plan
            elif planned:
                reason = "planner"
            else:
                reason = self._derive_skip_reason(tool, lane, degraded, safe_mode)
            normalized_reason = self._normalize_skip_reason(reason)
            gate_reason = self._normalize_gate_reason(normalized_reason)
            self._metric_call("inc_tool_skipped", tool.name, normalized_reason)
            self._metric_call("inc_frame_gate_skip", tool.name, gate_reason)
            if gate_reason == "rate_limit":
                self._metric_call("inc_tool_rate_limited", tool.name)
            self._inc_frame_stat(queued.frame.seq, "skipped")

        if not tools:
            return []

        lane_budget_ms = self._lane_budget_ms(plan, lane)
        lane_budget_deadline_ms = _now_ms() + max(1, lane_budget_ms)
        tasks: list[asyncio.Task[ToolResult]] = []
        task_meta: list[tuple[BaseTool, str, bool]] = []
        results: list[ToolResult] = []
        artifacts: FrameArtifacts | None = None
        if self._needs_preprocess(tools, planned_by_name):
            artifacts = await self._get_frame_artifacts(queued.frame)
        gate_frame = GateFrameContext(
            seq=queued.frame.seq,
            received_at_ms=now_ms,
            ttl_ms=queued.frame.ttl_ms,
            intent=intent,
            frame_fingerprint=fingerprint,
            safe_mode=safe_mode,
            degraded=degraded,
            meta=queued.frame.meta,
        )
        lane_enqueued_ms = int(queued.enqueued_at_ms_by_lane.get(lane.value, now_ms))
        for tool in tools:
            invocation = planned_by_name.get(tool.name)
            planned_timeout_ms = None
            if invocation is not None:
                planned_timeout_ms = max(1, int(invocation.timeout_ms))
            cache_key = self._cache_key(tool, queued.frame)
            decision = self._frame_gate.decide(tool=tool, frame=gate_frame, now_ms=now_ms)
            fault_active = bool(self._safe_call(self._faults, "has_active_fault", tool.name, default=False))
            input_variant = self._resolve_input_variant(tool, invocation)
            tool_frame = self._frame_with_variant(queued.frame, artifacts, input_variant)

            if decision.reuse_ok and cache_key and not fault_active:
                cached = self._tool_cache.get(
                    tool_name=tool.name,
                    cache_key=cache_key,
                    now_ms=now_ms,
                    max_age_ms=decision.max_age_ms,
                    fingerprint=fingerprint,
                )
                if cached is not None:
                    self._metric_call("inc_tool_cache_hit", tool.name)
                    cached_result = self._clone_tool_result_for_frame(cached.tool_result, queued.frame)
                    results.append(cached_result)
                    self._safe_call(self._degradation, "record_tool_result", cached_result)
                    continue
                self._metric_call("inc_tool_cache_miss", tool.name)

            if not decision.run:
                reason = self._normalize_gate_reason(decision.reason)
                self._metric_call("inc_tool_skipped", tool.name, reason)
                self._metric_call("inc_frame_gate_skip", tool.name, reason)
                if reason == "rate_limit":
                    self._metric_call("inc_tool_rate_limited", tool.name)
                self._inc_frame_stat(queued.frame.seq, "skipped")
                continue

            task = asyncio.create_task(
                self._run_single_tool(
                    tool=tool,
                    queued=queued,
                    lane=lane,
                    lane_budget_deadline_ms=lane_budget_deadline_ms,
                    planned_timeout_ms=planned_timeout_ms,
                    frame_input=tool_frame,
                    enqueued_at_ms=lane_enqueued_ms,
                )
            )
            self._active_by_seq[queued.frame.seq].add(task)
            self._task_lane[task] = lane
            task.add_done_callback(lambda done_task: self._task_lane.pop(done_task, None))
            tasks.append(task)
            task_meta.append((tool, cache_key, decision.reuse_ok))
            self._frame_gate.record_run(tool.name, fingerprint, now_ms=now_ms)

        gathered = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
        for index, item in enumerate(gathered):
            if isinstance(item, ToolResult):
                results.append(item)
                self._safe_call(self._degradation, "record_tool_result", item)
                tool, cache_key, reuse_ok = task_meta[index]
                if reuse_ok and cache_key and item.status == ToolStatus.OK:
                    self._tool_cache.set(
                        tool_name=tool.name,
                        cache_key=cache_key,
                        tool_result=item,
                        produced_events=[],
                        produced_at_ms=now_ms,
                        fingerprint=fingerprint,
                    )
        for task in tasks:
            self._task_lane.pop(task, None)

        session_id = self._session_id_from_meta(queued.frame.meta)
        if self._world_state is not None:
            try:
                self._world_state.ingest_tool_results(
                    session_id=session_id,
                    results=results,
                    now_ms=now_ms,
                    frame_meta=queued.frame.meta,
                )
            except Exception:  # noqa: BLE001
                pass
        self._active_by_seq.pop(queued.frame.seq, None)
        return results

    def _emit_planner_unavailable_skips(
        self,
        frame: FrameInput,
        plan: ToolInvocationPlan | None,
        known_tool_names: set[str],
    ) -> None:
        if plan is None:
            return
        if bool(frame.meta.get("_planner_unavailable_accounted", False)):
            return
        diagnostics = plan.diagnostics if isinstance(plan.diagnostics, dict) else {}
        skipped = diagnostics.get("skipped_tools")
        if not isinstance(skipped, list):
            frame.meta["_planner_unavailable_accounted"] = True
            return
        for item in skipped:
            if not isinstance(item, dict):
                continue
            if str(item.get("reason", "")).strip().lower() != "unavailable":
                continue
            tool_name = str(item.get("tool", "")).strip().lower()
            if not tool_name:
                continue
            if tool_name in known_tool_names:
                continue
            self._metric_call("inc_tool_skipped", tool_name, "unavailable")
            self._inc_frame_stat(frame.seq, "skipped")
        frame.meta["_planner_unavailable_accounted"] = True

    @staticmethod
    def _planner_skip_reasons(plan: ToolInvocationPlan | None) -> dict[str, str]:
        if plan is None or not isinstance(plan.diagnostics, dict):
            return {}
        skipped = plan.diagnostics.get("skipped_tools")
        if not isinstance(skipped, list):
            return {}
        out: dict[str, str] = {}
        for item in skipped:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool", "")).strip().lower()
            if not tool_name:
                continue
            reason = str(item.get("reason", "")).strip().lower()
            if not reason:
                continue
            if tool_name not in out:
                out[tool_name] = reason
        return out

    async def _run_single_tool(
        self,
        tool: BaseTool,
        queued: _QueuedTask,
        lane: ToolLane,
        lane_budget_deadline_ms: int,
        planned_timeout_ms: int | None,
        frame_input: FrameInput | None = None,
        enqueued_at_ms: int | None = None,
    ) -> ToolResult:
        frame = frame_input if frame_input is not None else queued.frame
        start_exec_ms = _now_ms()
        queue_ms = max(0, start_exec_ms - int(enqueued_at_ms if enqueued_at_ms is not None else start_exec_ms))
        self._metric_call("observe_tool_queue", tool.name, lane.value, queue_ms)
        now = _now_ms()

        if self._faults is not None and self._faults.should_disconnect(tool.name):
            self._metric_call("inc_tool_skipped", tool.name, "disconnect")
            self._inc_frame_stat(frame.seq, "skipped")
            self._safe_call(self._degradation, "record_unavailable", tool.name)
            return ToolResult(
                toolName=tool.name,
                toolVersion=tool.version,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                latencyMs=0,
                confidence=0.0,
                status=ToolStatus.ERROR,
                error="unavailable",
                payload={},
            )

        lane_deadline = self._config.fast_lane_deadline_ms if lane == ToolLane.FAST else self._config.slow_lane_deadline_ms
        ttl_left_ms = frame.ts_capture_ms + frame.ttl_ms - now
        budget_left_ms = lane_budget_deadline_ms - now
        tool_timeout_ms = int(getattr(tool, "timeout_ms", lane_deadline))
        is_risk_tool = str(getattr(tool, "capability", "")).strip().lower() == "risk"
        if is_risk_tool:
            timeout_ms = min(tool_timeout_ms, ttl_left_ms)
        else:
            timeout_candidates = [
                tool_timeout_ms,
                lane_deadline,
                ttl_left_ms,
                budget_left_ms,
            ]
            if planned_timeout_ms is not None:
                timeout_candidates.append(int(planned_timeout_ms))
            timeout_ms = min(timeout_candidates)

        if timeout_ms <= 0:
            self._metric_call("inc_deadline_miss", lane.value)
            self._metric_call("inc_tool_skipped", tool.name, "ttl_expired")
            self._inc_frame_stat(frame.seq, "skipped")
            return ToolResult(
                toolName=tool.name,
                toolVersion=tool.version,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                latencyMs=0,
                confidence=0.0,
                status=ToolStatus.DROPPED_EXPIRED,
                payload={},
            )

        ctx = ToolContext(
            trace_id=queued.trace_id,
            span_id=queued.span_id,
            deadline_ms=now + timeout_ms,
            meta=frame.meta,
        )
        trace = TraceInfo(trace_id=queued.trace_id, span_id=queued.span_id, context=None)

        pre_skip_reason = self._safe_call(tool, "should_skip", frame, default=None)
        if isinstance(pre_skip_reason, str) and pre_skip_reason.strip():
            reason = self._normalize_skip_reason(pre_skip_reason)
            self._metric_call("inc_tool_skipped", tool.name, reason)
            self._inc_frame_stat(frame.seq, "skipped")
            return ToolResult(
                toolName=tool.name,
                toolVersion=tool.version,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                latencyMs=0,
                confidence=0.0,
                status=ToolStatus.CANCELLED,
                error=f"skipped:{reason}",
                payload={},
            )

        started = time.perf_counter()
        success_elapsed_ms = 0
        self._metric_call("inc_tool_invoked", tool.name)
        self._inc_frame_stat(frame.seq, "invoked")
        with self._tool_span(trace, tool, lane, frame, timeout_ms) as span:
            try:
                extra_delay_ms = self._faults.extra_slow_delay_ms(tool.name) if self._faults is not None else 0
                if extra_delay_ms > 0:
                    await asyncio.sleep(extra_delay_ms / 1000.0)

                if self._faults is not None and self._faults.should_timeout(tool.name):
                    raise asyncio.TimeoutError()

                result = await asyncio.wait_for(tool.infer(frame, ctx), timeout=timeout_ms / 1000.0)
                success_elapsed_ms = int((time.perf_counter() - started) * 1000)
                result.latencyMs = max(result.latencyMs, success_elapsed_ms)
                forced_conf = self._faults.low_conf_value(tool.name) if self._faults is not None else None
                if forced_conf is not None:
                    result.confidence = forced_conf
                forced_risk_level = self._faults.forced_risk_level(tool.name) if self._faults is not None else None
                if forced_risk_level and isinstance(result.payload, dict) and "riskText" in result.payload:
                    patched_payload = dict(result.payload)
                    patched_payload["riskLevel"] = forced_risk_level
                    result.payload = patched_payload
                if span is not None:
                    span.set_attribute("tool.timeout", False)
                    span.set_attribute("tool.status", result.status.value)
                    span.set_attribute("tool.latency_ms", result.latencyMs)
            except asyncio.TimeoutError:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._observe_tool_timing(tool.name, lane.value, queue_ms, elapsed_ms)
                self._safe_call(self._degradation, "record_timeout", tool.name)
                self._metric_call("inc_tool_timeout", tool.name)
                self._inc_frame_stat(frame.seq, "timeout")
                self._metric_call("observe_tool_latency", tool.name, elapsed_ms)
                if span is not None:
                    span.set_attribute("tool.timeout", True)
                    span.set_attribute("tool.status", ToolStatus.TIMEOUT.value)
                    span.set_attribute("tool.latency_ms", elapsed_ms)
                return ToolResult(
                    toolName=tool.name,
                    toolVersion=tool.version,
                    seq=frame.seq,
                    tsCaptureMs=frame.ts_capture_ms,
                    latencyMs=elapsed_ms,
                    confidence=0.0,
                    status=ToolStatus.TIMEOUT,
                    error="timeout",
                    payload={},
                )
            except asyncio.CancelledError:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._observe_tool_timing(tool.name, lane.value, queue_ms, elapsed_ms)
                self._metric_call("observe_tool_latency", tool.name, elapsed_ms)
                if span is not None:
                    span.set_attribute("tool.status", ToolStatus.CANCELLED.value)
                    span.set_attribute("tool.latency_ms", elapsed_ms)
                return ToolResult(
                    toolName=tool.name,
                    toolVersion=tool.version,
                    seq=frame.seq,
                    tsCaptureMs=frame.ts_capture_ms,
                    latencyMs=elapsed_ms,
                    confidence=0.0,
                    status=ToolStatus.CANCELLED,
                    error="cancelled",
                    payload={},
                )
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._observe_tool_timing(tool.name, lane.value, queue_ms, elapsed_ms)
                self._metric_call("observe_tool_latency", tool.name, elapsed_ms)
                if span is not None:
                    span.set_attribute("tool.status", ToolStatus.ERROR.value)
                    span.set_attribute("tool.error", str(exc))
                    span.set_attribute("tool.latency_ms", elapsed_ms)
                return ToolResult(
                    toolName=tool.name,
                    toolVersion=tool.version,
                    seq=frame.seq,
                    tsCaptureMs=frame.ts_capture_ms,
                    latencyMs=elapsed_ms,
                    confidence=0.0,
                    status=ToolStatus.ERROR,
                    error=str(exc),
                    payload={},
                )

        if success_elapsed_ms <= 0:
            success_elapsed_ms = int((time.perf_counter() - started) * 1000)
            result.latencyMs = max(result.latencyMs, success_elapsed_ms)
        self._observe_tool_timing(tool.name, lane.value, queue_ms, result.latencyMs)
        self._metric_call("observe_tool_latency", tool.name, result.latencyMs)

        if self._is_expired(frame.ts_capture_ms, frame.ttl_ms, _now_ms()):
            self._metric_call("inc_deadline_miss", lane.value)
            self._metric_call("inc_tool_skipped", tool.name, "ttl_expired")
            self._inc_frame_stat(frame.seq, "skipped")
            result.status = ToolStatus.DROPPED_EXPIRED
            result.payload = {}
            return result

        return result

    def _cancel_older_active(self, new_seq: int) -> None:
        for seq, tasks in list(self._active_by_seq.items()):
            if seq >= new_seq:
                continue
            for task in list(tasks):
                if not task.done():
                    task.cancel()
            frame = self._frame_by_seq.get(seq)
            if frame is not None:
                self._complete_frame(frame, "canceled")
            else:
                self._discard_frame_runtime(seq)

    def _should_skip_frame(self, frame: FrameInput) -> bool:
        if bool(frame.meta.get("preserveOld", False)):
            return False
        return frame.seq < self._latest_seq

    @staticmethod
    def _is_expired(ts_capture_ms: int, ttl_ms: int, now_ms: int) -> bool:
        return now_ms - ts_capture_ms > ttl_ms

    def _derive_skip_reason(self, tool: BaseTool, lane: ToolLane, degraded: bool, safe_mode: bool) -> str:
        if safe_mode and tool.capability != "risk":
            return "safe_mode"
        if degraded and lane == ToolLane.SLOW:
            return "degraded"
        return "policy"

    def _normalize_skip_reason(self, reason: str) -> str:
        normalized = reason.strip().lower().replace("-", "_")
        if normalized == "safe_mode_skip":
            return "safe_mode"
        if normalized == "degraded_skip":
            return "degraded"
        allowed = {
            "policy",
            "planner",
            "intent",
            "crosscheck",
            "stale",
            "throttled_skip",
            "budget_skip",
            "latency_pred_exceeds_budget",
            "preempt_window_active",
            self.PREEMPT_REASON,
            "degraded",
            "safe_mode",
            "disconnect",
            "ttl_expired",
            "max_inflight",
            "queue_drop",
            "unavailable",
        }
        if normalized in allowed:
            return normalized
        return "policy"

    def _normalize_gate_reason(self, reason: str) -> str:
        normalized = reason.strip().lower().replace("-", "_")
        allowed = {
            "intent_off",
            "rate_limit",
            "safe_mode",
            "unchanged",
            "ttl_risk",
            "policy",
            "latency_pred_exceeds_budget",
            "preempt_window_active",
            self.PREEMPT_REASON,
        }
        if normalized in allowed:
            return normalized
        return "policy"

    @staticmethod
    def _cache_key(tool: BaseTool, frame: FrameInput) -> str:
        if tool.name in {"real_det", "real_ocr", "real_depth"}:
            return str(frame.meta.get("fingerprint", ""))
        return ""

    async def _get_frame_artifacts(self, frame: FrameInput) -> FrameArtifacts | None:
        if self._frame_tracker is None or self._preprocessor is None:
            return None
        return await asyncio.to_thread(
            self._frame_tracker.get_or_build_artifacts,
            frame.seq,
            frame.frame_bytes,
            frame.meta,
            self._preprocessor,
        )

    def _needs_preprocess(self, tools: list[BaseTool], planned_by_name: dict[str, Any]) -> bool:
        for tool in tools:
            invocation = planned_by_name.get(tool.name)
            variant = self._resolve_input_variant(tool, invocation)
            if variant != "full":
                return True
        return False

    @staticmethod
    def _resolve_input_variant(tool: BaseTool, invocation: Any | None) -> str:
        candidate = "full"
        if invocation is not None:
            candidate = str(getattr(invocation, "input_variant", "full") or "full").strip().lower()
        if candidate in {"full", "det", "ocr", "depth"}:
            return candidate
        if tool.name == "real_det":
            return "det"
        if tool.name == "real_ocr":
            return "ocr"
        if tool.name == "real_depth":
            return "depth"
        return "full"

    @staticmethod
    def _frame_with_variant(frame: FrameInput, artifacts: FrameArtifacts | None, variant: str) -> FrameInput:
        if artifacts is None or variant == "full":
            return frame
        if variant == "det":
            payload = artifacts.det_jpeg_bytes
        elif variant == "ocr":
            payload = artifacts.ocr_jpeg_bytes
        elif variant == "depth":
            payload = artifacts.depth_jpeg_bytes
        else:
            payload = artifacts.full_bytes
        return FrameInput(
            seq=frame.seq,
            ts_capture_ms=frame.ts_capture_ms,
            ttl_ms=frame.ttl_ms,
            frame_bytes=payload,
            meta=frame.meta,
        )

    @staticmethod
    def _clone_tool_result_for_frame(result: ToolResult, frame: FrameInput) -> ToolResult:
        cloned = result.model_copy(deep=True)
        cloned.seq = frame.seq
        cloned.tsCaptureMs = frame.ts_capture_ms
        return cloned

    def _complete_frame(self, frame: FrameInput, outcome: str) -> None:
        self._record_recent_summary(frame.seq, outcome)
        if self._on_frame_terminal is not None:
            self._on_frame_terminal(frame, outcome)
        self._discard_frame_runtime(frame.seq)

    def _set_queue_depth_metrics(self) -> None:
        self._metric_call("set_queue_depth", ToolLane.FAST.value, self._fast_q.qsize())
        self._metric_call("set_queue_depth", ToolLane.SLOW.value, self._slow_q.qsize())
        self._set_preempt_window_gauge()

    def _set_preempt_window_gauge(self) -> None:
        if self._preempt_window is None:
            self._metric_call("set_preempt_window_active", 0)
            return
        is_active = bool(self._safe_call(self._preempt_window, "is_active", _now_ms(), default=False))
        self._metric_call("set_preempt_window_active", 1 if is_active else 0)

    def _is_preempt_window_active(self, now_ms: int) -> bool:
        if self._preempt_window is None:
            self._metric_call("set_preempt_window_active", 0)
            return False
        is_active = bool(self._safe_call(self._preempt_window, "is_active", int(now_ms), default=False))
        self._metric_call("set_preempt_window_active", 1 if is_active else 0)
        return is_active

    def _enter_preempt_window(self, now_ms: int) -> None:
        if self._preempt_window is None:
            return
        entered = bool(
            self._safe_call(
                self._preempt_window,
                "enter",
                int(now_ms),
                int(self._config.preempt_window_ms),
                self.PREEMPT_METRIC_REASON,
                default=False,
            )
        )
        self._metric_call("set_preempt_window_active", 1)
        if not entered:
            return
        self._metric_call("inc_preempt_enter", self.PREEMPT_METRIC_REASON)
        canceled = self._cancel_inflight_slow_tasks()
        dropped = self._drop_slow_queue()
        if canceled > 0:
            self._metric_call("inc_preempt_cancel_inflight", ToolLane.SLOW.value, canceled)
        if dropped > 0:
            self._metric_call("inc_preempt_drop_queued", ToolLane.SLOW.value, dropped)

    def _enqueue_slow_after_fast(self, queued: _QueuedTask) -> bool:
        if self._slow_q.qsize() >= self._config.slow_q_drop_threshold:
            self._metric_call("inc_backpressure_drop", ToolLane.SLOW.value)
            self._safe_call(self._degradation, "note_backpressure", ToolLane.SLOW.value)
            return False

        if not self._frame_has_slow_work(queued.frame):
            return False

        with contextlib.suppress(asyncio.QueueFull):
            self._slow_q.put_nowait(queued)
            queued.enqueued_at_ms_by_lane[ToolLane.SLOW.value] = _now_ms()
            self._set_queue_depth_metrics()
            return True
        return False

    def _frame_has_slow_work(self, frame: FrameInput) -> bool:
        _ = frame
        return bool(self._registry.all_lane_tools(ToolLane.SLOW))

    @staticmethod
    def _normalize_risk_level(value: object) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"info", "warn", "critical"}:
            return raw
        if raw in {"warning", "high"}:
            return "warn"
        return "warn"

    def _has_critical_risk_result(self, results: list[ToolResult]) -> bool:
        for result in results:
            if result.status != ToolStatus.OK:
                continue
            payload = result.payload if isinstance(result.payload, dict) else {}
            if "riskText" not in payload:
                continue
            if self._normalize_risk_level(payload.get("riskLevel", payload.get("severity"))) == "critical":
                return True
        return False

    def _record_critical_preempt_skip(self, frame: FrameInput) -> None:
        tool_names = sorted({tool.name for tool in self._registry.all_lane_tools(ToolLane.SLOW)})
        if not tool_names:
            return
        for tool_name in tool_names:
            self._metric_call("inc_tool_skipped", tool_name, self.PREEMPT_REASON)
            self._inc_frame_stat(frame.seq, "skipped")

    def _record_preempt_window_skip(self, frame: FrameInput) -> None:
        tool_names = sorted({tool.name for tool in self._registry.all_lane_tools(ToolLane.SLOW)})
        if not tool_names:
            return
        for tool_name in tool_names:
            self._metric_call("inc_tool_skipped", tool_name, "preempt_window_active")
            self._inc_frame_stat(frame.seq, "skipped")

    def _cancel_inflight_slow_tasks(self) -> int:
        canceled = 0
        for task, lane in list(self._task_lane.items()):
            if lane != ToolLane.SLOW:
                continue
            if task.done():
                continue
            task.cancel()
            canceled += 1
        return canceled

    def _drop_slow_queue(self) -> int:
        dropped = 0
        while True:
            try:
                queued = self._slow_q.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._slow_q.task_done()
            dropped += 1
            self._discard_frame_runtime(queued.frame.seq)
        self._set_queue_depth_metrics()
        return dropped

    def queue_depth_snapshot(self) -> dict[str, int]:
        return {
            ToolLane.FAST.value: self._fast_q.qsize(),
            ToolLane.SLOW.value: self._slow_q.qsize(),
        }

    @staticmethod
    def _drain_queue(queue: asyncio.Queue[_QueuedTask]) -> None:
        with contextlib.suppress(asyncio.QueueEmpty):
            while True:
                queue.get_nowait()
                queue.task_done()

    def _build_plan(self, frame: FrameInput) -> ToolInvocationPlan:
        if self._planner is None:
            return ToolInvocationPlan(
                seq=frame.seq,
                generated_at_ms=_now_ms(),
                fast_budget_ms=self._config.fast_budget_ms,
                slow_budget_ms=self._config.slow_budget_ms,
                invocations=[],
            )

        context = FrameContext(
            seq=frame.seq,
            ts_capture_ms=frame.ts_capture_ms,
            ttl_ms=frame.ttl_ms,
            meta=frame.meta,
        )
        state = self._current_degradation_state()
        health_status, health_reason = self._safe_call(
            self._degradation,
            "get_health",
            default=(state.value, "planner"),
        )
        recent = list(self._recent_summaries)
        tools = self._registry.list_descriptors()
        plan = self._planner.plan(
            context,
            state,
            recent,
            tools,
            health_status=str(health_status),
            health_reason=str(health_reason),
            world_state=self._world_state,
        )
        if isinstance(plan.diagnostics, dict):
            frame.meta["_plannerDiagnostics"] = dict(plan.diagnostics)
            hints = plan.diagnostics.get("actionHints")
            if isinstance(hints, list):
                frame.meta["_plannerActionHints"] = [dict(item) for item in hints if isinstance(item, dict)]
        return plan

    def _current_degradation_state(self) -> DegradationState:
        state = getattr(self._degradation, "state", None)
        if isinstance(state, DegradationState):
            return state
        return DegradationState.NORMAL

    def _lane_budget_ms(self, plan: ToolInvocationPlan | None, lane: ToolLane) -> int:
        if plan is None:
            return self._config.fast_budget_ms if lane == ToolLane.FAST else self._config.slow_budget_ms
        if lane == ToolLane.FAST:
            return max(1, int(plan.fast_budget_ms))
        return max(1, int(plan.slow_budget_ms))

    def _inc_frame_stat(self, seq: int, key: str) -> None:
        stats = self._frame_tool_stats.get(seq)
        if stats is None:
            return
        stats[key] = int(stats.get(key, 0)) + 1

    def _record_recent_summary(self, seq: int, outcome: str) -> None:
        stats = self._frame_tool_stats.get(seq, {})
        self._recent_summaries.append(
            RecentFrameSummary(
                seq=seq,
                completed_at_ms=_now_ms(),
                outcome=outcome,
                invoked=int(stats.get("invoked", 0)),
                timeout=int(stats.get("timeout", 0)),
                skipped=int(stats.get("skipped", 0)),
            )
        )

    def _discard_frame_runtime(self, seq: int) -> None:
        self._frame_by_seq.pop(seq, None)
        self._plan_by_seq.pop(seq, None)
        self._frame_tool_stats.pop(seq, None)

    @staticmethod
    def _session_id_from_meta(meta: dict[str, Any]) -> str:
        session_id = str(meta.get("sessionId", "")).strip()
        return session_id or "default"

    def _tool_span(self, trace: TraceInfo, tool: BaseTool, lane: ToolLane, frame: FrameInput, timeout_ms: int):
        if self._observability is None:
            return contextlib.nullcontext(None)
        return self._observability.start_span(
            "tool.infer",
            trace,
            tool_name=getattr(tool, "name", "tool"),
            tool_lane=lane.value,
            frame_seq=frame.seq,
            timeout_ms=timeout_ms,
        )

    def _observe_tool_timing(self, tool_name: str, lane: str, queue_ms: int, exec_ms: int) -> None:
        self._metric_call("observe_tool_exec", tool_name, lane, exec_ms)
        self._runtime_stats_call("observe", tool_name, lane, queue_ms, exec_ms)

    def _metric_call(self, method: str, *args: Any) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)

    def _runtime_stats_call(self, method: str, *args: Any) -> None:
        if self._runtime_stats is None:
            return
        fn = getattr(self._runtime_stats, method, None)
        if callable(fn):
            fn(*args)

    @staticmethod
    def _safe_call(target: Any | None, method: str, *args: Any, default: Any = None) -> Any:
        if target is None:
            return default
        fn = getattr(target, method, None)
        if not callable(fn):
            return default
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001
            return default


def should_run_mode_target(
    *,
    frame_seq: int,
    mode: str | None,
    target: str,
    profile: "ModeProfile | None",
    force_on_mode_change: bool = False,
) -> bool:
    normalized_seq = max(1, int(frame_seq))
    if profile is None:
        return True
    stride = profile.stride_for(mode, target)
    if stride is None:
        return True
    if force_on_mode_change:
        return True
    return ((normalized_seq - 1) % max(1, int(stride))) == 0
