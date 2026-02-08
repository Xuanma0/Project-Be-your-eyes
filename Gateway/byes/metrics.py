from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest


@dataclass
class MetricsResponse:
    content: bytes
    content_type: str


class GatewayMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or CollectorRegistry(auto_describe=True)
        self.byes_e2e_latency_ms = Histogram(
            "byes_e2e_latency_ms",
            "Gateway end-to-end latency in milliseconds",
            buckets=(20, 50, 100, 200, 350, 500, 800, 1200, 2000, 3000, 5000),
            registry=self._registry,
        )
        self.byes_ttfa_ms = Histogram(
            "byes_ttfa_ms",
            "Gateway time-to-first-action in milliseconds",
            buckets=(5, 10, 20, 35, 50, 80, 120, 200, 350, 500, 800, 1200, 2000),
            registry=self._registry,
        )
        self.byes_ttfa_count_total = Counter(
            "byes_ttfa_count_total",
            "TTFA accounting by outcome and action kind",
            labelnames=("outcome", "kind"),
            registry=self._registry,
        )
        self.byes_ttfa_outcome_total = Counter(
            "byes_ttfa_outcome_total",
            "Per-frame TTFA outcome accounting",
            labelnames=("outcome", "kind"),
            registry=self._registry,
        )
        self.byes_tool_latency_ms = Histogram(
            "byes_tool_latency_ms",
            "Tool latency in milliseconds",
            labelnames=("tool",),
            buckets=(10, 20, 50, 100, 200, 350, 500, 800, 1200, 2000, 3000),
            registry=self._registry,
        )
        self.byes_preprocess_latency_ms = Histogram(
            "byes_preprocess_latency_ms",
            "Frame preprocess latency in milliseconds",
            buckets=(1, 2, 5, 10, 20, 50, 100, 200, 350, 500),
            registry=self._registry,
        )
        self.byes_preprocess_bytes_total = Counter(
            "byes_preprocess_bytes_total",
            "Total preprocess output bytes by variant",
            labelnames=("variant",),
            registry=self._registry,
        )
        self.byes_preprocess_cache_hit_total = Counter(
            "byes_preprocess_cache_hit_total",
            "Frame preprocess cache hit count",
            registry=self._registry,
        )
        self.byes_preprocess_decode_error_total = Counter(
            "byes_preprocess_decode_error_total",
            "Frame preprocess decode fallback count",
            registry=self._registry,
        )
        self.byes_deadline_miss_total = Counter(
            "byes_deadline_miss_total",
            "Number of missed deadlines/TTL drops",
            labelnames=("lane",),
            registry=self._registry,
        )
        self.byes_safemode_enter_total = Counter(
            "byes_safemode_enter_total",
            "Number of times gateway entered SAFE_MODE",
            registry=self._registry,
        )
        self.byes_queue_depth = Gauge(
            "byes_queue_depth",
            "Current queue depth by lane",
            labelnames=("lane",),
            registry=self._registry,
        )
        self.byes_backpressure_drop_total = Counter(
            "byes_backpressure_drop_total",
            "Dropped tasks caused by backpressure",
            labelnames=("lane",),
            registry=self._registry,
        )
        self.byes_frame_received_total = Counter(
            "byes_frame_received_total",
            "Number of frames accepted by /api/frame",
            registry=self._registry,
        )
        self.byes_frame_completed_total = Counter(
            "byes_frame_completed_total",
            "Number of frames completed by final outcome",
            labelnames=("outcome",),
            registry=self._registry,
        )
        self.byes_tool_invoked_total = Counter(
            "byes_tool_invoked_total",
            "Number of tool invocations attempted",
            labelnames=("tool",),
            registry=self._registry,
        )
        self.byes_tool_timeout_total = Counter(
            "byes_tool_timeout_total",
            "Number of tool timeouts",
            labelnames=("tool",),
            registry=self._registry,
        )
        self.byes_tool_skipped_total = Counter(
            "byes_tool_skipped_total",
            "Number of skipped tools",
            labelnames=("tool", "reason"),
            registry=self._registry,
        )
        self.byes_tool_cache_hit_total = Counter(
            "byes_tool_cache_hit_total",
            "Number of tool cache hits",
            labelnames=("tool",),
            registry=self._registry,
        )
        self.byes_tool_cache_miss_total = Counter(
            "byes_tool_cache_miss_total",
            "Number of tool cache misses",
            labelnames=("tool",),
            registry=self._registry,
        )
        self.byes_tool_rate_limited_total = Counter(
            "byes_tool_rate_limited_total",
            "Number of rate-limited tool decisions",
            labelnames=("tool",),
            registry=self._registry,
        )
        self.byes_planner_select_total = Counter(
            "byes_planner_select_total",
            "Planner selected tool count by reason",
            labelnames=("tool", "reason"),
            registry=self._registry,
        )
        self.byes_planner_skip_total = Counter(
            "byes_planner_skip_total",
            "Planner skipped tool count by reason",
            labelnames=("tool", "reason"),
            registry=self._registry,
        )
        self.byes_frame_gate_skip_total = Counter(
            "byes_frame_gate_skip_total",
            "Number of frame-gate skips",
            labelnames=("tool", "reason"),
            registry=self._registry,
        )
        self.byes_fault_set_total = Counter(
            "byes_fault_set_total",
            "Fault injection set count",
            labelnames=("tool", "mode"),
            registry=self._registry,
        )
        self.byes_fault_trigger_total = Counter(
            "byes_fault_trigger_total",
            "Fault injection trigger count",
            labelnames=("tool", "mode"),
            registry=self._registry,
        )
        self.byes_degradation_state_change_total = Counter(
            "byes_degradation_state_change_total",
            "Degradation state change count",
            labelnames=("from_state", "to_state", "reason"),
            registry=self._registry,
        )
        self.byes_health_warn_total = Counter(
            "byes_health_warn_total",
            "Health warning count",
            labelnames=("status",),
            registry=self._registry,
        )
        self.byes_frame_meta_present_total = Counter(
            "byes_frame_meta_present_total",
            "Frames with valid parsed FrameMeta",
            registry=self._registry,
        )
        self.byes_frame_meta_missing_total = Counter(
            "byes_frame_meta_missing_total",
            "Frames without FrameMeta",
            registry=self._registry,
        )
        self.byes_frame_meta_parse_error_total = Counter(
            "byes_frame_meta_parse_error_total",
            "FrameMeta parse failures",
            registry=self._registry,
        )
        self.byes_crosscheck_conflict_total = Counter(
            "byes_crosscheck_conflict_total",
            "Cross-check conflict detections",
            labelnames=("kind",),
            registry=self._registry,
        )
        self.byes_active_confirm_total = Counter(
            "byes_active_confirm_total",
            "Active confirm strategy events",
            labelnames=("kind",),
            registry=self._registry,
        )
        self.byes_actionplan_patched_total = Counter(
            "byes_actionplan_patched_total",
            "Action plan patch count",
            labelnames=("reason",),
            registry=self._registry,
        )
        self.byes_actiongate_block_total = Counter(
            "byes_actiongate_block_total",
            "Action-plan gate block count",
            labelnames=("reason",),
            registry=self._registry,
        )
        self.byes_actiongate_patch_total = Counter(
            "byes_actiongate_patch_total",
            "Action-plan gate patch count",
            labelnames=("reason",),
            registry=self._registry,
        )
        self.byes_throttle_enter_total = Counter(
            "byes_throttle_enter_total",
            "SLO governor throttle enter count",
            registry=self._registry,
        )
        self.byes_throttle_state_gauge = Gauge(
            "byes_throttle_state_gauge",
            "SLO governor state gauge",
            labelnames=("state",),
            registry=self._registry,
        )
        self.byes_slo_violation_total = Counter(
            "byes_slo_violation_total",
            "SLO violation count by kind",
            labelnames=("kind",),
            registry=self._registry,
        )
        self.byes_hazard_emit_total = Counter(
            "byes_hazard_emit_total",
            "Risk events emitted after hazard-memory filtering",
            labelnames=("kind",),
            registry=self._registry,
        )
        self.byes_hazard_suppressed_total = Counter(
            "byes_hazard_suppressed_total",
            "Risk hazards suppressed by hazard-memory policy",
            labelnames=("reason",),
            registry=self._registry,
        )
        self.byes_hazard_active_gauge = Gauge(
            "byes_hazard_active_gauge",
            "Current active hazards tracked in memory",
            registry=self._registry,
        )
        self.byes_hazard_persist_total = Counter(
            "byes_hazard_persist_total",
            "Hazards kept active by grace window",
            labelnames=("kind",),
            registry=self._registry,
        )
        self.byes_hazard_active_gauge.set(0)
        self.byes_throttle_state_gauge.labels(state="NORMAL").set(1)
        self.byes_throttle_state_gauge.labels(state="THROTTLED").set(0)

    def observe_e2e_latency(self, latency_ms: int) -> None:
        self.byes_e2e_latency_ms.observe(max(0, latency_ms))

    def observe_ttfa(self, latency_ms: int) -> None:
        self.byes_ttfa_ms.observe(max(0, latency_ms))

    def inc_ttfa_count(self, outcome: str, kind: str) -> None:
        self.byes_ttfa_count_total.labels(outcome=outcome, kind=kind).inc()

    def inc_ttfa_outcome(self, outcome: str, kind: str) -> None:
        self.byes_ttfa_outcome_total.labels(outcome=outcome, kind=kind).inc()

    def observe_tool_latency(self, tool: str, latency_ms: int) -> None:
        self.byes_tool_latency_ms.labels(tool=tool).observe(max(0, latency_ms))

    def observe_preprocess_latency(self, latency_ms: int) -> None:
        self.byes_preprocess_latency_ms.observe(max(0, latency_ms))

    def inc_preprocess_bytes(self, variant: str, size_bytes: int) -> None:
        self.byes_preprocess_bytes_total.labels(variant=variant).inc(max(0, int(size_bytes)))

    def inc_preprocess_cache_hit(self) -> None:
        self.byes_preprocess_cache_hit_total.inc()

    def inc_preprocess_decode_error(self) -> None:
        self.byes_preprocess_decode_error_total.inc()

    def inc_deadline_miss(self, lane: str) -> None:
        self.byes_deadline_miss_total.labels(lane=lane).inc()

    def inc_safemode_enter(self) -> None:
        self.byes_safemode_enter_total.inc()

    def set_queue_depth(self, lane: str, depth: int) -> None:
        self.byes_queue_depth.labels(lane=lane).set(max(0, depth))

    def inc_backpressure_drop(self, lane: str) -> None:
        self.byes_backpressure_drop_total.labels(lane=lane).inc()

    def inc_frame_received(self) -> None:
        self.byes_frame_received_total.inc()

    def inc_frame_completed(self, outcome: str) -> None:
        self.byes_frame_completed_total.labels(outcome=outcome).inc()

    def inc_tool_invoked(self, tool: str) -> None:
        self.byes_tool_invoked_total.labels(tool=tool).inc()

    def inc_tool_timeout(self, tool: str) -> None:
        self.byes_tool_timeout_total.labels(tool=tool).inc()

    def inc_tool_skipped(self, tool: str, reason: str) -> None:
        self.byes_tool_skipped_total.labels(tool=tool, reason=reason).inc()

    def inc_tool_cache_hit(self, tool: str) -> None:
        self.byes_tool_cache_hit_total.labels(tool=tool).inc()

    def inc_tool_cache_miss(self, tool: str) -> None:
        self.byes_tool_cache_miss_total.labels(tool=tool).inc()

    def inc_tool_rate_limited(self, tool: str) -> None:
        self.byes_tool_rate_limited_total.labels(tool=tool).inc()

    def inc_planner_select(self, tool: str, reason: str) -> None:
        self.byes_planner_select_total.labels(tool=tool, reason=reason).inc()

    def inc_planner_skip(self, tool: str, reason: str) -> None:
        self.byes_planner_skip_total.labels(tool=tool, reason=reason).inc()

    def inc_frame_gate_skip(self, tool: str, reason: str) -> None:
        self.byes_frame_gate_skip_total.labels(tool=tool, reason=reason).inc()

    def inc_fault_set(self, tool: str, mode: str) -> None:
        self.byes_fault_set_total.labels(tool=tool, mode=mode).inc()

    def inc_fault_trigger(self, tool: str, mode: str) -> None:
        self.byes_fault_trigger_total.labels(tool=tool, mode=mode).inc()

    def inc_degradation_state_change(self, from_state: str, to_state: str, reason: str) -> None:
        self.byes_degradation_state_change_total.labels(
            from_state=from_state,
            to_state=to_state,
            reason=reason,
        ).inc()

    def inc_health_warn(self, status: str) -> None:
        self.byes_health_warn_total.labels(status=status).inc()

    def inc_frame_meta_present(self) -> None:
        self.byes_frame_meta_present_total.inc()

    def inc_frame_meta_missing(self) -> None:
        self.byes_frame_meta_missing_total.inc()

    def inc_frame_meta_parse_error(self) -> None:
        self.byes_frame_meta_parse_error_total.inc()

    def inc_crosscheck_conflict(self, kind: str) -> None:
        self.byes_crosscheck_conflict_total.labels(kind=kind).inc()

    def inc_active_confirm(self, kind: str) -> None:
        self.byes_active_confirm_total.labels(kind=kind).inc()

    def inc_actionplan_patched(self, reason: str) -> None:
        self.byes_actionplan_patched_total.labels(reason=reason).inc()

    def inc_actiongate_block(self, reason: str) -> None:
        self.byes_actiongate_block_total.labels(reason=reason).inc()

    def inc_actiongate_patch(self, reason: str) -> None:
        self.byes_actiongate_patch_total.labels(reason=reason).inc()

    def inc_throttle_enter(self) -> None:
        self.byes_throttle_enter_total.inc()

    def set_throttle_state(self, state: str, value: int) -> None:
        self.byes_throttle_state_gauge.labels(state=state).set(max(0, int(value)))

    def inc_slo_violation(self, kind: str) -> None:
        self.byes_slo_violation_total.labels(kind=kind).inc()

    def inc_hazard_emit(self, kind: str) -> None:
        self.byes_hazard_emit_total.labels(kind=kind).inc()

    def inc_hazard_suppressed(self, reason: str) -> None:
        self.byes_hazard_suppressed_total.labels(reason=reason).inc()

    def set_hazard_active(self, value: int) -> None:
        self.byes_hazard_active_gauge.set(max(0, int(value)))

    def inc_hazard_persist(self, kind: str) -> None:
        self.byes_hazard_persist_total.labels(kind=kind).inc()

    def render(self) -> MetricsResponse:
        return MetricsResponse(
            content=generate_latest(self._registry),
            content_type=CONTENT_TYPE_LATEST,
        )
