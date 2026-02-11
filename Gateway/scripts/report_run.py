from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.quality_metrics import (  # noqa: E402
    compute_depth_risk_metrics,
    compute_ocr_metrics,
    compute_quality_score,
    extract_event_schema_stats,
    extract_inference_summary_from_ws_events,
    infer_inference_summary_from_events_v1,
    extract_safety_behavior_from_ws_events,
    extract_ocr_intent_frames_from_ws_events,
    extract_pred_hazards_from_ws_events,
    extract_pred_ocr_from_ws_events,
    load_gt_ocr_jsonl,
    load_gt_risk_jsonl,
)

_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"((?:\\.|[^\"])*)\"")

SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


def parse_metric_labels(raw_labels: str | None) -> dict[str, str]:
    if not raw_labels:
        return {}
    labels: dict[str, str] = {}
    for key, value in _LABEL_RE.findall(raw_labels):
        labels[key] = value.replace('\\"', '"').replace('\\\\', '\\')
    return labels


def parse_metric_value(raw_value: str) -> float | None:
    normalized = raw_value.strip()
    if normalized in {"+Inf", "Inf", "+inf", "inf"}:
        return float("inf")
    if normalized in {"-Inf", "-inf"}:
        return float("-inf")
    if normalized in {"NaN", "nan"}:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def make_series_key(metric_name: str, labels: dict[str, str]) -> SeriesKey:
    return metric_name, tuple(sorted(labels.items(), key=lambda item: item[0]))


def parse_prometheus_text_to_map(text: str) -> dict[SeriesKey, float]:
    rows: dict[SeriesKey, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parsed = parse_prometheus_line(line)
        if parsed is None:
            continue

        metric_name, labels, value = parsed
        if value is None:
            continue

        rows[make_series_key(metric_name, labels)] = value
    return rows


def parse_prometheus_line(line: str) -> tuple[str, dict[str, str], float | None] | None:
    parts = line.split()
    if len(parts) < 2:
        return None

    name_and_labels = parts[0]
    raw_value = parts[1]

    metric_name = name_and_labels
    labels: dict[str, str] = {}
    if "{" in name_and_labels and name_and_labels.endswith("}"):
        brace_index = name_and_labels.find("{")
        metric_name = name_and_labels[:brace_index]
        labels = parse_metric_labels(name_and_labels[brace_index:])

    if not metric_name:
        return None
    value = parse_metric_value(raw_value)
    return metric_name, labels, value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def pick_health_status(event: dict[str, Any]) -> str:
    health_status = event.get("healthStatus")
    if isinstance(health_status, str):
        normalized = health_status.strip().upper()
        if normalized in {"NORMAL", "THROTTLED", "DEGRADED", "SAFE_MODE", "WAITING_CLIENT"}:
            return normalized

    summary = str(event.get("summary", ""))
    status = str(event.get("status", ""))

    payload = event.get("payload")
    if isinstance(payload, dict):
        payload_health_status = payload.get("healthStatus")
        if isinstance(payload_health_status, str):
            normalized = payload_health_status.strip().upper()
            if normalized in {"NORMAL", "THROTTLED", "DEGRADED", "SAFE_MODE", "WAITING_CLIENT"}:
                return normalized
        payload_status = payload.get("status")
        if isinstance(payload_status, str) and payload_status:
            status = payload_status

    text = " ".join([summary, status]).strip().lower()
    if "safe_mode" in text:
        return "SAFE_MODE"
    if "throttled" in text:
        return "THROTTLED"
    if "degraded" in text:
        return "DEGRADED"
    if "normal" in text:
        return "NORMAL"
    if "waiting_client" in text:
        return "WAITING_CLIENT"
    if text:
        return "HEALTH_OTHER"
    return "HEALTH_UNKNOWN"


def pick_health_reason(event: dict[str, Any]) -> str:
    reason = event.get("healthReason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()

    payload = event.get("payload")
    if isinstance(payload, dict):
        payload_reason = payload.get("healthReason")
        if isinstance(payload_reason, str) and payload_reason.strip():
            return payload_reason.strip()
        payload_reason = payload.get("reason")
        if isinstance(payload_reason, str) and payload_reason.strip():
            return payload_reason.strip()

    summary = str(event.get("summary", "")).strip()
    start = summary.rfind("(")
    end = summary.rfind(")")
    if start >= 0 and end > start:
        parsed = summary[start + 1 : end].strip()
        if parsed:
            return parsed
    return "unknown"


def collect_ws_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    event_type_counter: Counter[str] = Counter()
    state_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()
    action_plan_category_counter: Counter[str] = Counter()
    expired_emitted = 0
    first_safe_mode_ms: int | None = None
    safe_mode_active = False
    perception_after_safe_mode = 0
    action_plan_after_safe_mode = 0
    confirm_request_after_safe_mode = 0
    active_confirm_events = 0
    confirm_request_events = 0
    hazard_events = 0
    unique_hazard_ids: set[str] = set()

    for row in rows:
        event = row.get("event")
        if not isinstance(event, dict):
            continue

        event_type = str(event.get("type", "unknown"))
        event_type_counter[event_type] += 1
        if bool(event.get("activeConfirm")):
            active_confirm_events += 1
        hazard_kind = event.get("hazardKind")
        hazard_id = event.get("hazardId")
        if event_type == "risk" and isinstance(hazard_kind, str) and hazard_kind.strip():
            hazard_events += 1
        if isinstance(hazard_id, str) and hazard_id.strip():
            unique_hazard_ids.add(hazard_id.strip())

        if event_type == "health":
            health_state = pick_health_status(event)
            state_counter[health_state] += 1
            reason_counter[pick_health_reason(event)] += 1
            if health_state == "SAFE_MODE":
                if first_safe_mode_ms is None:
                    first_safe_mode_ms = _row_time_ms(row, event)
                safe_mode_active = True
            elif health_state in {"NORMAL", "DEGRADED"}:
                safe_mode_active = False
        elif event_type == "perception" and safe_mode_active:
            perception_after_safe_mode += 1
        elif event_type == "action_plan" and safe_mode_active:
            action_plan_after_safe_mode += 1
        if event_type == "action_plan":
            if event.get("confirmId"):
                confirm_request_events += 1
                if safe_mode_active:
                    confirm_request_after_safe_mode += 1
            category = str(
                event.get("actionCategory")
                or event.get("reason")
                or event.get("summary")
                or "unknown"
            ).strip()
            action_plan_category_counter[category] += 1

        recv_ms = row.get("receivedAtMs")
        event_ts = event.get("timestampMs")
        ttl_ms = event.get("ttlMs")
        if isinstance(recv_ms, int) and isinstance(event_ts, int) and isinstance(ttl_ms, int):
            if ttl_ms <= 0 or recv_ms - event_ts > ttl_ms:
                expired_emitted += 1

    return {
        "total_rows": len(rows),
        "event_types": dict(sorted(event_type_counter.items(), key=lambda item: item[0])),
        "states": dict(sorted(state_counter.items(), key=lambda item: item[0])),
        "health_reasons_topk": reason_counter.most_common(8),
        "expired_emitted": expired_emitted,
        "safe_mode_first_ms": first_safe_mode_ms,
        "safe_mode_perception_violations": perception_after_safe_mode,
        "safe_mode_actionplan_violations": action_plan_after_safe_mode,
        "safe_mode_confirm_request_violations": confirm_request_after_safe_mode,
        "active_confirm_events": active_confirm_events,
        "confirm_request_events": confirm_request_events,
        "hazard_events": hazard_events,
        "unique_hazards": len(unique_hazard_ids),
        "action_plan_categories": dict(sorted(action_plan_category_counter.items(), key=lambda item: item[0])),
    }


def _row_time_ms(row: dict[str, Any], event: dict[str, Any]) -> int:
    recv_ms = row.get("receivedAtMs")
    if isinstance(recv_ms, int):
        return recv_ms
    event_ts = event.get("timestampMs")
    if isinstance(event_ts, int):
        return event_ts
    return 0


def aggregate_metric_sum(samples: dict[SeriesKey, float], metric_name: str) -> float:
    total = 0.0
    for (name, _labels), value in samples.items():
        if name == metric_name:
            total += value
    return total


def metric_series_count(samples: dict[SeriesKey, float], metric_name: str) -> int:
    count = 0
    for (name, _labels), _value in samples.items():
        if name == metric_name:
            count += 1
    return count


def render_metric_sum(samples: dict[SeriesKey, float], metric_name: str, delta: bool = False) -> str:
    series_count = metric_series_count(samples, metric_name)
    suffix = "delta sum" if delta else "sum"
    if series_count == 0:
        return f"- `{metric_name}` {suffix}: `0` (series absent)"
    return f"- `{metric_name}` {suffix}: `{format_float(aggregate_metric_sum(samples, metric_name))}`"


def metric_details(samples: dict[SeriesKey, float], metric_name: str) -> list[tuple[dict[str, str], float]]:
    out: list[tuple[dict[str, str], float]] = []
    for (name, labels), value in samples.items():
        if name == metric_name:
            out.append((dict(labels), value))
    out.sort(key=lambda item: tuple(sorted(item[0].items(), key=lambda kv: kv[0])))
    return out


def metric_value_with_labels(samples: dict[SeriesKey, float], metric_name: str, labels: dict[str, str]) -> float | None:
    key = make_series_key(metric_name, labels)
    if key not in samples:
        return None
    return samples[key]


def append_metric_details(
    lines: list[str],
    samples: dict[SeriesKey, float],
    metric_name: str,
    label_names: list[str],
    value_label: str,
) -> None:
    details = metric_details(samples, metric_name)
    if not details:
        return
    lines.append(f"- `{metric_name}` details:")
    for labels, value in details:
        label_text = ", ".join([f"{name}=`{labels.get(name, '')}`" for name in label_names])
        lines.append(f"  - {label_text}: {value_label}=`{format_float(value)}`")


def compute_delta(before: dict[SeriesKey, float], after: dict[SeriesKey, float]) -> dict[SeriesKey, float]:
    delta: dict[SeriesKey, float] = {}
    for key, after_value in after.items():
        before_value = before.get(key, 0.0)
        value = after_value - before_value
        if value < 0:
            value = after_value
        delta[key] = value
    return delta


def format_float(value: float) -> str:
    if value == float("inf"):
        return "inf"
    if value == float("-inf"):
        return "-inf"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_report(
    markdown_title: str,
    ws_jsonl: Path,
    metrics_source: str,
    ws_stats: dict[str, Any],
    after_samples: dict[SeriesKey, float],
    delta_samples: dict[SeriesKey, float] | None,
    external_readiness: dict[str, Any] | None,
    run_package_summary: dict[str, Any] | None,
) -> str:
    lines: list[str] = []
    lines.append(f"# {markdown_title}")
    lines.append("")
    lines.append("## Inputs")
    lines.append(f"- ws jsonl: `{ws_jsonl}`")
    lines.append(f"- metrics source: `{metrics_source}`")
    lines.append("")
    if run_package_summary is not None:
        lines.append("## Run Package Summary")
        lines.append(f"- run package: `{run_package_summary.get('runPackageDir', '')}`")
        source_zip = run_package_summary.get("sourceZip")
        if isinstance(source_zip, str) and source_zip.strip():
            lines.append(f"- source zip: `{source_zip}`")
        lines.append(f"- scenarioTag: `{run_package_summary.get('scenarioTag', '')}`")
        lines.append(f"- startMs: `{run_package_summary.get('startMs', '')}`")
        lines.append(f"- endMs: `{run_package_summary.get('endMs', '')}`")
        lines.append(f"- frameCountSent: `{run_package_summary.get('frameCountSent', '')}`")
        lines.append(f"- eventCountAccepted: `{run_package_summary.get('eventCountAccepted', '')}`")
        lines.append(f"- localSafetyFallbackEnterCount: `{run_package_summary.get('localSafetyFallbackEnterCount', '')}`")
        health_counts = run_package_summary.get("healthStatusCounts", {})
        if isinstance(health_counts, dict):
            lines.append(f"- healthStatusCounts: `{json.dumps(health_counts, ensure_ascii=False)}`")
        errors = run_package_summary.get("errors", [])
        if isinstance(errors, list):
            lines.append(f"- errors: `{json.dumps(errors, ensure_ascii=False)}`")
        lines.append("")

    lines.append("## External Readiness")
    if not external_readiness:
        lines.append("- unavailable")
    else:
        tools = external_readiness.get("tools", {})
        if isinstance(tools, dict) and tools:
            for tool_name in sorted(tools.keys()):
                item = tools.get(tool_name)
                if not isinstance(item, dict):
                    continue
                lines.append(
                    "- `{0}`: ready=`{1}`, warmed_up=`{2}`, backend=`{3}`, model_id=`{4}`, reason=`{5}`".format(
                        tool_name,
                        item.get("ready", False),
                        item.get("warmed_up", False),
                        item.get("backend", ""),
                        item.get("model_id", ""),
                        item.get("reason", ""),
                    )
                )
        else:
            lines.append("- no configured real_* tools")
    lines.append("")

    lines.append("## WS Summary")
    lines.append(f"- total rows: `{ws_stats['total_rows']}`")
    lines.append(f"- expired emitted events: `{ws_stats['expired_emitted']}`")
    lines.append("- event type counts:")
    for key, value in ws_stats["event_types"].items():
        lines.append(f"  - `{key}`: `{value}`")
    lines.append("- healthStatus counts:")
    for key, value in ws_stats["states"].items():
        lines.append(f"  - `{key}`: `{value}`")
    lines.append("- healthReason topK:")
    for reason, count in ws_stats["health_reasons_topk"]:
        lines.append(f"  - `{reason}`: `{count}`")
    lines.append("- safe-mode perception violations:")
    lines.append(f"  - `first_safe_mode_ms`: `{ws_stats['safe_mode_first_ms']}`")
    lines.append(f"  - `perception_after_safe_mode`: `{ws_stats['safe_mode_perception_violations']}`")
    lines.append("- safe-mode action-plan violations:")
    lines.append(f"  - `action_plan_after_safe_mode`: `{ws_stats['safe_mode_actionplan_violations']}`")
    lines.append("- safe-mode confirm-request violations:")
    lines.append(f"  - `confirm_request_after_safe_mode`: `{ws_stats['safe_mode_confirm_request_violations']}`")
    lines.append(f"- active_confirm_events: `{ws_stats['active_confirm_events']}`")
    lines.append(f"- confirm_request_events: `{ws_stats['confirm_request_events']}`")
    lines.append(f"- hazard_events: `{ws_stats['hazard_events']}`")
    lines.append(f"- unique_hazards: `{ws_stats['unique_hazards']}`")
    lines.append(f"- action-plan events: `{ws_stats['event_types'].get('action_plan', 0)}`")
    lines.append("- action-plan categories:")
    for key, value in ws_stats["action_plan_categories"].items():
        lines.append(f"  - `{key}`: `{value}`")
    lines.append(f"- dialog events: `{ws_stats['event_types'].get('dialog', 0)}`")
    lines.append("")

    lines.append("## Metrics Snapshot - Raw After")
    for metric_name in [
        "byes_frame_received_total",
        "byes_frame_completed_total",
        "byes_frame_meta_present_total",
        "byes_frame_meta_missing_total",
        "byes_frame_meta_parse_error_total",
        "byes_preprocess_cache_hit_total",
        "byes_preprocess_decode_error_total",
        "byes_preprocess_bytes_total",
        "byes_tool_invoked_total",
        "byes_tool_timeout_total",
        "byes_tool_skipped_total",
        "byes_preempt_enter_total",
        "byes_preempt_window_active_gauge",
        "byes_preempt_cancel_inflight_total",
        "byes_preempt_drop_queued_total",
        "byes_critical_latch_active_gauge",
        "byes_critical_latch_enter_total",
        "byes_risklevel_upgrade_total",
        "byes_tool_queue_ms_count",
        "byes_tool_queue_ms_sum",
        "byes_tool_exec_ms_count",
        "byes_tool_exec_ms_sum",
        "byes_tool_cache_hit_total",
        "byes_tool_cache_miss_total",
        "byes_tool_rate_limited_total",
        "byes_planner_select_total",
        "byes_planner_skip_total",
        "byes_frame_gate_skip_total",
        "byes_ttfa_count_total",
        "byes_ttfa_outcome_total",
        "byes_throttle_enter_total",
        "byes_throttle_state_gauge",
        "byes_slo_violation_total",
        "byes_safemode_enter_total",
        "byes_deadline_miss_total",
        "byes_backpressure_drop_total",
        "byes_fault_set_total",
        "byes_fault_trigger_total",
        "byes_health_warn_total",
        "byes_crosscheck_conflict_total",
        "byes_active_confirm_total",
        "byes_actionplan_patched_total",
        "byes_confirm_request_total",
        "byes_confirm_response_total",
        "byes_confirm_timeout_total",
        "byes_confirm_pending_gauge",
        "byes_confirm_suppressed_total",
        "byes_actiongate_block_total",
        "byes_actiongate_patch_total",
        "byes_hazard_emit_total",
        "byes_hazard_suppressed_total",
        "byes_hazard_active_gauge",
        "byes_hazard_persist_total",
    ]:
        lines.append(render_metric_sum(after_samples, metric_name))

    e2e_after_count = aggregate_metric_sum(after_samples, "byes_e2e_latency_ms_count")
    e2e_after_sum = aggregate_metric_sum(after_samples, "byes_e2e_latency_ms_sum")
    lines.append(f"- `byes_e2e_latency_ms_count`: `{format_float(e2e_after_count)}`")
    lines.append(f"- `byes_e2e_latency_ms_sum`: `{format_float(e2e_after_sum)}`")
    lines.append(f"- `byes_e2e_latency_ms_bucket` sum: `{format_float(aggregate_metric_sum(after_samples, 'byes_e2e_latency_ms_bucket'))}`")
    ttfa_after_count = aggregate_metric_sum(after_samples, "byes_ttfa_ms_count")
    ttfa_after_sum = aggregate_metric_sum(after_samples, "byes_ttfa_ms_sum")
    lines.append(f"- `byes_ttfa_ms_count`: `{format_float(ttfa_after_count)}`")
    lines.append(f"- `byes_ttfa_ms_sum`: `{format_float(ttfa_after_sum)}`")
    lines.append(f"- `byes_ttfa_ms_bucket` sum: `{format_float(aggregate_metric_sum(after_samples, 'byes_ttfa_ms_bucket'))}`")
    preprocess_after_count = aggregate_metric_sum(after_samples, "byes_preprocess_latency_ms_count")
    preprocess_after_sum = aggregate_metric_sum(after_samples, "byes_preprocess_latency_ms_sum")
    lines.append(f"- `byes_preprocess_latency_ms_count`: `{format_float(preprocess_after_count)}`")
    lines.append(f"- `byes_preprocess_latency_ms_sum`: `{format_float(preprocess_after_sum)}`")
    lines.append(
        f"- `byes_preprocess_latency_ms_bucket` sum: "
        f"`{format_float(aggregate_metric_sum(after_samples, 'byes_preprocess_latency_ms_bucket'))}`"
    )

    append_metric_details(lines, after_samples, "byes_frame_completed_total", ["outcome"], "count")
    append_metric_details(lines, after_samples, "byes_preprocess_bytes_total", ["variant"], "count")
    append_metric_details(lines, after_samples, "byes_tool_invoked_total", ["tool"], "count")
    append_metric_details(lines, after_samples, "byes_tool_timeout_total", ["tool"], "count")
    append_metric_details(lines, after_samples, "byes_tool_skipped_total", ["tool", "reason"], "count")
    append_metric_details(lines, after_samples, "byes_preempt_enter_total", ["reason"], "count")
    append_metric_details(lines, after_samples, "byes_preempt_window_active_gauge", [], "count")
    append_metric_details(lines, after_samples, "byes_preempt_cancel_inflight_total", ["lane"], "count")
    append_metric_details(lines, after_samples, "byes_preempt_drop_queued_total", ["lane"], "count")
    append_metric_details(lines, after_samples, "byes_critical_latch_active_gauge", [], "count")
    append_metric_details(lines, after_samples, "byes_critical_latch_enter_total", ["reason"], "count")
    append_metric_details(
        lines,
        after_samples,
        "byes_risklevel_upgrade_total",
        ["from_level", "to_level", "reason"],
        "count",
    )
    append_metric_details(lines, after_samples, "byes_tool_queue_ms_count", ["tool", "lane"], "count")
    append_metric_details(lines, after_samples, "byes_tool_exec_ms_count", ["tool", "lane"], "count")
    append_metric_details(lines, after_samples, "byes_tool_cache_hit_total", ["tool"], "count")
    append_metric_details(lines, after_samples, "byes_tool_cache_miss_total", ["tool"], "count")
    append_metric_details(lines, after_samples, "byes_tool_rate_limited_total", ["tool"], "count")
    append_metric_details(lines, after_samples, "byes_planner_select_total", ["tool", "reason"], "count")
    append_metric_details(lines, after_samples, "byes_planner_skip_total", ["tool", "reason"], "count")
    append_metric_details(lines, after_samples, "byes_frame_gate_skip_total", ["tool", "reason"], "count")
    append_metric_details(lines, after_samples, "byes_crosscheck_conflict_total", ["kind"], "count")
    append_metric_details(lines, after_samples, "byes_active_confirm_total", ["kind"], "count")
    append_metric_details(lines, after_samples, "byes_actionplan_patched_total", ["reason"], "count")
    append_metric_details(lines, after_samples, "byes_confirm_request_total", ["kind"], "count")
    append_metric_details(lines, after_samples, "byes_confirm_response_total", ["kind", "answer"], "count")
    append_metric_details(lines, after_samples, "byes_confirm_timeout_total", ["kind"], "count")
    append_metric_details(lines, after_samples, "byes_confirm_pending_gauge", [], "count")
    append_metric_details(lines, after_samples, "byes_confirm_suppressed_total", ["reason"], "count")
    append_metric_details(lines, after_samples, "byes_actiongate_block_total", ["reason"], "count")
    append_metric_details(lines, after_samples, "byes_actiongate_patch_total", ["reason"], "count")
    append_metric_details(lines, after_samples, "byes_ttfa_count_total", ["outcome", "kind"], "count")
    append_metric_details(lines, after_samples, "byes_ttfa_outcome_total", ["outcome", "kind"], "count")
    append_metric_details(lines, after_samples, "byes_throttle_state_gauge", ["state"], "count")
    append_metric_details(lines, after_samples, "byes_slo_violation_total", ["kind"], "count")
    append_metric_details(lines, after_samples, "byes_hazard_emit_total", ["kind"], "count")
    append_metric_details(lines, after_samples, "byes_hazard_suppressed_total", ["reason"], "count")
    append_metric_details(lines, after_samples, "byes_hazard_persist_total", ["kind"], "count")
    _append_tool_focus(lines, after_samples, tool="real_det", delta=False)
    _append_tool_focus(lines, after_samples, tool="real_ocr", delta=False)
    _append_tool_focus(lines, after_samples, tool="real_depth", delta=False)
    _append_tool_focus(lines, after_samples, tool="real_vlm", delta=False)

    raw_changes = metric_details(after_samples, "byes_degradation_state_change_total")
    if raw_changes:
        lines.append("- `byes_degradation_state_change_total` details:")
        for labels, value in raw_changes:
            lines.append(
                "  - `{0} -> {1}` reason=`{2}` count=`{3}`".format(
                    labels.get("from_state", ""),
                    labels.get("to_state", ""),
                    labels.get("reason", ""),
                    format_float(value),
                )
            )
    lines.append("")

    lines.append("## Metrics Snapshot - Run Delta")
    if delta_samples is None:
        lines.append("- delta mode disabled (provide both `--metrics-before` and `--metrics-after`)" )
    else:
        for metric_name in [
            "byes_frame_received_total",
            "byes_frame_completed_total",
            "byes_frame_meta_present_total",
            "byes_frame_meta_missing_total",
            "byes_frame_meta_parse_error_total",
            "byes_preprocess_cache_hit_total",
            "byes_preprocess_decode_error_total",
            "byes_preprocess_bytes_total",
            "byes_tool_invoked_total",
            "byes_tool_timeout_total",
            "byes_tool_skipped_total",
            "byes_preempt_enter_total",
            "byes_preempt_window_active_gauge",
            "byes_preempt_cancel_inflight_total",
            "byes_preempt_drop_queued_total",
            "byes_critical_latch_active_gauge",
            "byes_critical_latch_enter_total",
            "byes_risklevel_upgrade_total",
            "byes_tool_queue_ms_count",
            "byes_tool_queue_ms_sum",
            "byes_tool_exec_ms_count",
            "byes_tool_exec_ms_sum",
            "byes_tool_cache_hit_total",
            "byes_tool_cache_miss_total",
            "byes_tool_rate_limited_total",
            "byes_planner_select_total",
            "byes_planner_skip_total",
            "byes_frame_gate_skip_total",
            "byes_ttfa_count_total",
            "byes_ttfa_outcome_total",
            "byes_throttle_enter_total",
            "byes_throttle_state_gauge",
            "byes_slo_violation_total",
            "byes_safemode_enter_total",
            "byes_deadline_miss_total",
            "byes_backpressure_drop_total",
            "byes_fault_set_total",
            "byes_fault_trigger_total",
            "byes_health_warn_total",
            "byes_crosscheck_conflict_total",
            "byes_active_confirm_total",
            "byes_actionplan_patched_total",
            "byes_confirm_request_total",
            "byes_confirm_response_total",
            "byes_confirm_timeout_total",
            "byes_confirm_pending_gauge",
            "byes_confirm_suppressed_total",
            "byes_actiongate_block_total",
            "byes_actiongate_patch_total",
            "byes_hazard_emit_total",
            "byes_hazard_suppressed_total",
            "byes_hazard_active_gauge",
            "byes_hazard_persist_total",
        ]:
            lines.append(render_metric_sum(delta_samples, metric_name, delta=True))

        e2e_delta_count = aggregate_metric_sum(delta_samples, "byes_e2e_latency_ms_count")
        e2e_delta_sum = aggregate_metric_sum(delta_samples, "byes_e2e_latency_ms_sum")
        lines.append(f"- `byes_e2e_latency_ms_count` delta: `{format_float(e2e_delta_count)}`")
        lines.append(f"- `byes_e2e_latency_ms_sum` delta: `{format_float(e2e_delta_sum)}`")
        lines.append(
            f"- `byes_e2e_latency_ms_bucket` delta sum: "
            f"`{format_float(aggregate_metric_sum(delta_samples, 'byes_e2e_latency_ms_bucket'))}`"
        )
        ttfa_delta_count = aggregate_metric_sum(delta_samples, "byes_ttfa_ms_count")
        ttfa_delta_sum = aggregate_metric_sum(delta_samples, "byes_ttfa_ms_sum")
        lines.append(f"- `byes_ttfa_ms_count` delta: `{format_float(ttfa_delta_count)}`")
        lines.append(f"- `byes_ttfa_ms_sum` delta: `{format_float(ttfa_delta_sum)}`")
        lines.append(
            f"- `byes_ttfa_ms_bucket` delta sum: "
            f"`{format_float(aggregate_metric_sum(delta_samples, 'byes_ttfa_ms_bucket'))}`"
        )
        preprocess_delta_count = aggregate_metric_sum(delta_samples, "byes_preprocess_latency_ms_count")
        preprocess_delta_sum = aggregate_metric_sum(delta_samples, "byes_preprocess_latency_ms_sum")
        lines.append(f"- `byes_preprocess_latency_ms_count` delta: `{format_float(preprocess_delta_count)}`")
        lines.append(f"- `byes_preprocess_latency_ms_sum` delta: `{format_float(preprocess_delta_sum)}`")
        lines.append(
            f"- `byes_preprocess_latency_ms_bucket` delta sum: "
            f"`{format_float(aggregate_metric_sum(delta_samples, 'byes_preprocess_latency_ms_bucket'))}`"
        )

        append_metric_details(lines, delta_samples, "byes_frame_completed_total", ["outcome"], "delta")
        append_metric_details(lines, delta_samples, "byes_preprocess_bytes_total", ["variant"], "delta")
        append_metric_details(lines, delta_samples, "byes_tool_invoked_total", ["tool"], "delta")
        append_metric_details(lines, delta_samples, "byes_tool_timeout_total", ["tool"], "delta")
        append_metric_details(lines, delta_samples, "byes_tool_skipped_total", ["tool", "reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_preempt_enter_total", ["reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_preempt_window_active_gauge", [], "delta")
        append_metric_details(lines, delta_samples, "byes_preempt_cancel_inflight_total", ["lane"], "delta")
        append_metric_details(lines, delta_samples, "byes_preempt_drop_queued_total", ["lane"], "delta")
        append_metric_details(lines, delta_samples, "byes_critical_latch_active_gauge", [], "delta")
        append_metric_details(lines, delta_samples, "byes_critical_latch_enter_total", ["reason"], "delta")
        append_metric_details(
            lines,
            delta_samples,
            "byes_risklevel_upgrade_total",
            ["from_level", "to_level", "reason"],
            "delta",
        )
        append_metric_details(lines, delta_samples, "byes_tool_queue_ms_count", ["tool", "lane"], "delta")
        append_metric_details(lines, delta_samples, "byes_tool_exec_ms_count", ["tool", "lane"], "delta")
        append_metric_details(lines, delta_samples, "byes_tool_cache_hit_total", ["tool"], "delta")
        append_metric_details(lines, delta_samples, "byes_tool_cache_miss_total", ["tool"], "delta")
        append_metric_details(lines, delta_samples, "byes_tool_rate_limited_total", ["tool"], "delta")
        append_metric_details(lines, delta_samples, "byes_planner_select_total", ["tool", "reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_planner_skip_total", ["tool", "reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_frame_gate_skip_total", ["tool", "reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_crosscheck_conflict_total", ["kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_active_confirm_total", ["kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_actionplan_patched_total", ["reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_confirm_request_total", ["kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_confirm_response_total", ["kind", "answer"], "delta")
        append_metric_details(lines, delta_samples, "byes_confirm_timeout_total", ["kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_confirm_pending_gauge", [], "delta")
        append_metric_details(lines, delta_samples, "byes_confirm_suppressed_total", ["reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_actiongate_block_total", ["reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_actiongate_patch_total", ["reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_ttfa_count_total", ["outcome", "kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_ttfa_outcome_total", ["outcome", "kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_throttle_state_gauge", ["state"], "delta")
        append_metric_details(lines, delta_samples, "byes_slo_violation_total", ["kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_hazard_emit_total", ["kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_hazard_suppressed_total", ["reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_hazard_persist_total", ["kind"], "delta")
        _append_tool_focus(lines, delta_samples, tool="real_det", delta=True)
        _append_tool_focus(lines, delta_samples, tool="real_ocr", delta=True)
        _append_tool_focus(lines, delta_samples, tool="real_depth", delta=True)
        _append_tool_focus(lines, delta_samples, tool="real_vlm", delta=True)
        completed_delta_total = aggregate_metric_sum(delta_samples, "byes_frame_completed_total")
        ttfa_outcome_delta = aggregate_metric_sum(delta_samples, "byes_ttfa_outcome_total")
        ttfa_consistent = abs(ttfa_outcome_delta - completed_delta_total) <= 1e-9
        lines.append(
            f"- `ttfa_outcome_equals_frame_completed`: `{ttfa_consistent}` "
            f"(ttfa_outcome_delta=`{format_float(ttfa_outcome_delta)}`, frame_completed_delta=`{format_float(completed_delta_total)}`)"
        )

        delta_changes = metric_details(delta_samples, "byes_degradation_state_change_total")
        if delta_changes:
            lines.append("- `byes_degradation_state_change_total` delta details:")
            for labels, value in delta_changes:
                lines.append(
                    "  - `{0} -> {1}` reason=`{2}` delta=`{3}`".format(
                        labels.get("from_state", ""),
                        labels.get("to_state", ""),
                        labels.get("reason", ""),
                        format_float(value),
                    )
                )
    lines.append("")

    return "\n".join(lines)


def build_summary_payload(
    ws_stats: dict[str, Any],
    after_samples: dict[SeriesKey, float],
    delta_samples: dict[SeriesKey, float] | None,
    run_package_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = delta_samples if delta_samples is not None else after_samples
    frame_received = aggregate_metric_sum(source, "byes_frame_received_total")
    frame_completed = aggregate_metric_sum(source, "byes_frame_completed_total")
    e2e_count = aggregate_metric_sum(source, "byes_e2e_latency_ms_count")
    e2e_sum = aggregate_metric_sum(source, "byes_e2e_latency_ms_sum")
    ttfa_count = aggregate_metric_sum(source, "byes_ttfa_ms_count")
    ttfa_sum = aggregate_metric_sum(source, "byes_ttfa_ms_sum")
    safemode_enter = aggregate_metric_sum(source, "byes_safemode_enter_total")
    throttle_enter = aggregate_metric_sum(source, "byes_throttle_enter_total")
    preempt_enter = aggregate_metric_sum(source, "byes_preempt_enter_total")
    confirm_request = aggregate_metric_sum(source, "byes_confirm_request_total")
    confirm_response = aggregate_metric_sum(source, "byes_confirm_response_total")
    confirm_timeout = aggregate_metric_sum(source, "byes_confirm_timeout_total")
    frame_meta_present = aggregate_metric_sum(source, "byes_frame_meta_present_total")
    frame_meta_missing = aggregate_metric_sum(source, "byes_frame_meta_missing_total")
    frame_meta_parse_error = aggregate_metric_sum(source, "byes_frame_meta_parse_error_total")

    ttfa_outcomes: dict[str, float] = {}
    for labels, value in metric_details(source, "byes_ttfa_outcome_total"):
        outcome = labels.get("outcome", "")
        kind = labels.get("kind", "")
        key = f"{outcome}:{kind}"
        ttfa_outcomes[key] = value

    confirm_missed = max(0.0, confirm_request - confirm_response)
    safety_score = 100.0
    safety_score -= safemode_enter * 35.0
    safety_score -= throttle_enter * 10.0
    safety_score -= preempt_enter * 8.0
    safety_score -= confirm_timeout * 6.0
    safety_score -= confirm_missed * 2.0
    safety_score -= (ws_stats.get("safe_mode_perception_violations", 0) + ws_stats.get("safe_mode_actionplan_violations", 0)) * 3.0
    safety_score = max(0.0, min(100.0, safety_score))

    payload: dict[str, Any] = {
        "frame_received": frame_received,
        "frame_completed": frame_completed,
        "e2e_count": e2e_count,
        "e2e_sum": e2e_sum,
        "ttfa_count": ttfa_count,
        "ttfa_sum": ttfa_sum,
        "ttfa_outcomes": ttfa_outcomes,
        "safemode_enter": safemode_enter,
        "throttle_enter": throttle_enter,
        "preempt_enter": preempt_enter,
        "confirm_request": confirm_request,
        "confirm_response": confirm_response,
        "confirm_timeout": confirm_timeout,
        "frame_meta_present": frame_meta_present,
        "frame_meta_missing": frame_meta_missing,
        "frame_meta_parse_error": frame_meta_parse_error,
        "ws_total_rows": ws_stats.get("total_rows", 0),
        "ws_event_types": ws_stats.get("event_types", {}),
        "ws_health_status_counts": ws_stats.get("states", {}),
        "safe_mode_first_ms": ws_stats.get("safe_mode_first_ms"),
        "perception_after_safe_mode": ws_stats.get("safe_mode_perception_violations", 0),
        "action_plan_after_safe_mode": ws_stats.get("safe_mode_actionplan_violations", 0),
        "confirm_request_after_safe_mode": ws_stats.get("safe_mode_confirm_request_violations", 0),
        "safety_score": round(safety_score, 2),
    }
    if run_package_summary is not None:
        payload["scenarioTag"] = run_package_summary.get("scenarioTag", "")
        payload["runPackageDir"] = run_package_summary.get("runPackageDir", "")
        if run_package_summary.get("sourceZip"):
            payload["sourceZip"] = run_package_summary.get("sourceZip")
    return payload


def generate_report_outputs(
    *,
    ws_jsonl: Path,
    output: Path,
    metrics_url: str,
    metrics_before_path: Path | None,
    metrics_after_path: Path | None,
    external_readiness_url: str | None,
    run_package_summary: dict[str, Any] | None,
    output_json: Path | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    ws_rows = load_jsonl(ws_jsonl)
    ws_stats = collect_ws_stats(ws_rows)
    event_schema_source = "wsEventsJsonl"
    event_source_path = ws_jsonl
    events_v1_rel: str | None = None
    if isinstance(run_package_summary, dict):
        src = str(run_package_summary.get("eventSchemaSource", "")).strip()
        candidate = str(run_package_summary.get("eventSchemaInputPath", "")).strip()
        rel = str(run_package_summary.get("eventsV1Path", "")).strip()
        if src in {"eventsV1Jsonl", "wsEventsJsonl"}:
            event_schema_source = src
        if candidate:
            candidate_path = Path(candidate)
            if candidate_path.exists():
                event_source_path = candidate_path
        if rel:
            events_v1_rel = rel

    if metrics_before_path is not None and metrics_after_path is not None:
        if not metrics_before_path.exists():
            raise FileNotFoundError(f"metrics before file not found: {metrics_before_path}")
        if not metrics_after_path.exists():
            raise FileNotFoundError(f"metrics after file not found: {metrics_after_path}")
        before_text = load_text(metrics_before_path)
        after_text = load_text(metrics_after_path)
        metrics_source = f"before={metrics_before_path}, after={metrics_after_path}"
    else:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(metrics_url)
            response.raise_for_status()
            after_text = response.text
        before_text = ""
        metrics_source = metrics_url

    after_samples = parse_prometheus_text_to_map(after_text)
    delta_samples = None
    if before_text:
        before_samples = parse_prometheus_text_to_map(before_text)
        delta_samples = compute_delta(before_samples, after_samples)

    external_readiness: dict[str, Any] | None = None
    readiness_url = external_readiness_url or _derive_external_readiness_url(metrics_url)
    if readiness_url:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(readiness_url)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    external_readiness = payload
        except Exception:
            external_readiness = None

    report_title = f"Run Report - {ws_jsonl.stem}"
    report_text = build_report(
        report_title,
        ws_jsonl,
        metrics_source,
        ws_stats,
        after_samples,
        delta_samples,
        external_readiness,
        run_package_summary,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report_text + "\n", encoding="utf-8")

    summary = build_summary_payload(ws_stats, after_samples, delta_samples, run_package_summary)
    inferred_summary = extract_inference_summary_from_ws_events(event_source_path)
    events_v1_inferred = infer_inference_summary_from_events_v1(load_jsonl(event_source_path))
    summary["inference"] = _merge_inference_summary(inferred_summary, events_v1_inferred)
    event_schema_stats = extract_event_schema_stats(event_source_path)
    event_schema_stats["source"] = event_schema_source
    event_schema_stats["eventsV1Path"] = events_v1_rel if event_schema_source == "eventsV1Jsonl" else None
    extra_event_warnings = []
    if isinstance(run_package_summary, dict):
        warnings_raw = run_package_summary.get("eventSchemaWarnings", [])
        if isinstance(warnings_raw, list):
            extra_event_warnings = [str(item) for item in warnings_raw if str(item).strip()]
    if extra_event_warnings:
        event_schema_stats["warningsCount"] = int(event_schema_stats.get("warningsCount", 0) or 0) + len(extra_event_warnings)
    gt_cfg = (run_package_summary or {}).get("groundTruth", {})
    base_safety_behavior = extract_safety_behavior_from_ws_events(event_source_path)
    quality_payload: dict[str, Any] = {"hasGroundTruth": False, "safetyBehavior": base_safety_behavior, "eventSchema": event_schema_stats}
    if isinstance(gt_cfg, dict) and bool(gt_cfg.get("hasGroundTruth")):
        try:
            frames_total = int(round(float(summary.get("frame_received", 0) or 0)))
        except Exception:
            frames_total = 0
        if frames_total <= 0 and isinstance(run_package_summary, dict):
            try:
                frames_total = int(run_package_summary.get("frameCountSent", 0) or 0)
            except Exception:
                frames_total = 0

        ocr_path_raw = str(gt_cfg.get("ocrPath", "")).strip()
        risk_path_raw = str(gt_cfg.get("riskPath", "")).strip()
        ocr_gt = load_gt_ocr_jsonl(Path(ocr_path_raw)) if ocr_path_raw else {}
        risk_gt: dict[int, list[dict[str, Any]]] = {}
        risk_norm_meta = {"unknownKinds": [], "aliasHits": [], "warningsCount": 0}
        if risk_path_raw:
            risk_gt_result = load_gt_risk_jsonl(Path(risk_path_raw), return_meta=True)
            if isinstance(risk_gt_result, tuple):
                risk_gt, risk_norm_meta = risk_gt_result
            else:
                risk_gt = risk_gt_result
        pred_ocr = extract_pred_ocr_from_ws_events(event_source_path)
        ocr_intent_frames = extract_ocr_intent_frames_from_ws_events(event_source_path)
        pred_hazard_result = extract_pred_hazards_from_ws_events(event_source_path, return_meta=True)
        pred_hazards: dict[int, list[dict[str, Any]]] = {}
        pred_norm_meta = {"unknownKinds": [], "aliasHits": [], "warningsCount": 0}
        if isinstance(pred_hazard_result, tuple):
            pred_hazards, pred_norm_meta = pred_hazard_result
        else:
            pred_hazards = pred_hazard_result
        ocr_metrics = compute_ocr_metrics(ocr_gt, pred_ocr, frames_total, intent_frames=ocr_intent_frames) if ocr_gt else None
        risk_metrics = None
        window = int(gt_cfg.get("matchWindowFrames", 2) or 2)
        if risk_gt:
            merged_norm = _merge_hazard_normalization_meta(risk_norm_meta, pred_norm_meta)
            risk_metrics = compute_depth_risk_metrics(risk_gt, pred_hazards, window, normalization=merged_norm)
            event_schema_stats["warningsCount"] = int(event_schema_stats.get("warningsCount", 0) or 0) + int(
                merged_norm.get("warningsCount", 0) or 0
            )
        critical_frames = _collect_critical_gt_frames(risk_gt) if risk_gt else None
        safety_behavior = extract_safety_behavior_from_ws_events(
            event_source_path,
            critical_frame_seqs=critical_frames if critical_frames else None,
            near_window_frames=window,
        )

        safety_score = float(summary.get("safety_score", 100.0) or 100.0)
        quality_score, breakdown = compute_quality_score(safety_score, ocr_metrics, risk_metrics, safety_behavior=safety_behavior)
        top_findings = _build_quality_top_findings(ocr_metrics, risk_metrics, safety_behavior)
        quality_payload = {
            "hasGroundTruth": True,
            "ocr": ocr_metrics,
            "depthRisk": risk_metrics,
            "safetyBehavior": safety_behavior,
            "eventSchema": event_schema_stats,
            "topFindings": top_findings,
            "qualityScore": quality_score,
            "qualityScoreBreakdown": breakdown,
        }
    else:
        quality_payload["topFindings"] = _build_quality_top_findings(None, None, base_safety_behavior)
    summary["quality"] = quality_payload

    json_path: Path | None = output_json
    if json_path is None:
        json_path = output.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output, json_path, summary


def _merge_inference_summary(
    primary: dict[str, dict[str, str | None]],
    fallback: dict[str, dict[str, str | None]],
) -> dict[str, dict[str, str | None]]:
    merged: dict[str, dict[str, str | None]] = {}
    for tool_name in ("ocr", "risk"):
        primary_bucket = primary.get(tool_name, {}) if isinstance(primary, dict) else {}
        fallback_bucket = fallback.get(tool_name, {}) if isinstance(fallback, dict) else {}
        bucket = {
            "backend": _coalesce_inference_field(primary_bucket, fallback_bucket, "backend"),
            "model": _coalesce_inference_field(primary_bucket, fallback_bucket, "model"),
            "endpoint": _coalesce_inference_field(primary_bucket, fallback_bucket, "endpoint"),
        }
        merged[tool_name] = bucket
    return merged


def _coalesce_inference_field(
    primary_bucket: dict[str, Any],
    fallback_bucket: dict[str, Any],
    key: str,
) -> str | None:
    primary_value = str(primary_bucket.get(key, "")).strip() if isinstance(primary_bucket, dict) else ""
    if primary_value:
        return primary_value
    fallback_value = str(fallback_bucket.get(key, "")).strip() if isinstance(fallback_bucket, dict) else ""
    if fallback_value:
        return fallback_value
    return None


def _append_tool_focus(lines: list[str], samples: dict[SeriesKey, float], tool: str, delta: bool) -> None:
    suffix = "delta" if delta else "count"
    invoked = metric_value_with_labels(samples, "byes_tool_invoked_total", {"tool": tool})
    timeout = metric_value_with_labels(samples, "byes_tool_timeout_total", {"tool": tool})
    skipped_total = 0.0
    skipped_found = False
    for labels, value in metric_details(samples, "byes_tool_skipped_total"):
        if labels.get("tool") == tool:
            skipped_total += value
            skipped_found = True

    if invoked is None and timeout is None and not skipped_found:
        return

    lines.append(f"- {tool} focus:")
    lines.append(
        f"  - `byes_tool_invoked_total{{tool={tool}}}` {suffix}: "
        f"`{format_float(invoked if invoked is not None else 0.0)}`"
    )
    lines.append(
        f"  - `byes_tool_timeout_total{{tool={tool}}}` {suffix}: "
        f"`{format_float(timeout if timeout is not None else 0.0)}`"
    )
    lines.append(
        f"  - `byes_tool_skipped_total{{tool={tool},*}}` {suffix}: "
        f"`{format_float(skipped_total if skipped_found else 0.0)}`"
    )


def derive_output_path(ws_jsonl: Path, output: str | None, run_package_dir: Path | None) -> Path:
    if output:
        return Path(output)
    if run_package_dir is not None:
        return run_package_dir / "report.md"
    return Path(f"report_{ws_jsonl.stem}.md")


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _collect_critical_gt_frames(risk_gt: dict[int, list[dict[str, Any]]]) -> set[int]:
    critical_frames: set[int] = set()
    for seq, hazards in risk_gt.items():
        for hazard in hazards:
            severity = str(hazard.get("severity", "")).strip().lower()
            if severity == "critical":
                critical_frames.add(int(seq))
                break
    return critical_frames


def _merge_hazard_normalization_meta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(
        {
            str(item).strip().lower()
            for item in list(left.get("unknownKinds", []) or []) + list(right.get("unknownKinds", []) or [])
            if str(item).strip()
        }
    )
    alias_counts: dict[tuple[str, str], int] = {}
    for source in (left, right):
        rows = source.get("aliasHits", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            from_kind = str(row.get("from", "")).strip().lower()
            to_kind = str(row.get("to", "")).strip().lower()
            if not from_kind or not to_kind:
                continue
            key = (from_kind, to_kind)
            alias_counts[key] = alias_counts.get(key, 0) + int(row.get("count", 0) or 0)
    alias_hits = [
        {"from": from_kind, "to": to_kind, "count": count}
        for (from_kind, to_kind), count in sorted(alias_counts.items(), key=lambda item: (item[0][0], item[0][1]))
    ]
    warnings_count = int(left.get("warningsCount", 0) or 0) + int(right.get("warningsCount", 0) or 0)
    return {"unknownKinds": unknown, "aliasHits": alias_hits, "warningsCount": warnings_count}


def _build_quality_top_findings(
    ocr_metrics: dict[str, Any] | None,
    risk_metrics: dict[str, Any] | None,
    safety_behavior: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    confirm = safety_behavior.get("confirm", {}) if isinstance(safety_behavior, dict) else {}
    timeouts = int(confirm.get("timeouts", 0) or 0)
    timeout_samples = confirm.get("timeoutFrameSeqSample", []) if isinstance(confirm, dict) else []
    missing = int(confirm.get("missingResponseCount", 0) or 0)
    missing_samples = confirm.get("missingFrameSeqSample", []) if isinstance(confirm, dict) else []

    if timeouts > 0:
        findings.append(
            {
                "severity": "critical",
                "type": "confirm_timeout",
                "frameSeq": int(timeout_samples[0]) if isinstance(timeout_samples, list) and timeout_samples else None,
                "message": f"confirm timeout count={timeouts}",
                "evidence": {"timeouts": timeouts},
            }
        )
    if missing > 0:
        findings.append(
            {
                "severity": "warning",
                "type": "missing_confirm_response",
                "frameSeq": int(missing_samples[0]) if isinstance(missing_samples, list) and missing_samples else None,
                "message": f"missing confirm responses={missing}",
                "evidence": {"missingResponseCount": missing},
            }
        )

    if isinstance(risk_metrics, dict):
        critical = risk_metrics.get("critical", {})
        miss_critical = int(critical.get("missCriticalCount", 0) or 0)
        gt_critical = int(critical.get("gtCriticalCount", 0) or 0)
        latch = safety_behavior.get("latch", {}) if isinstance(safety_behavior, dict) else {}
        preempt = safety_behavior.get("preempt", {}) if isinstance(safety_behavior, dict) else {}
        latch_near = int(latch.get("nearCriticalCount", 0) or 0) if isinstance(latch, dict) else 0
        preempt_near = int(preempt.get("nearCriticalCount", 0) or 0) if isinstance(preempt, dict) else 0
        if gt_critical > 0 and miss_critical > 0 and (latch_near + preempt_near == 0):
            findings.append(
                {
                    "severity": "critical",
                    "type": "miss_critical_no_latch",
                    "frameSeq": None,
                    "message": "critical GT misses without near-critical latch/preempt",
                    "evidence": {
                        "missCriticalCount": miss_critical,
                        "nearCriticalLatch": latch_near,
                        "nearCriticalPreempt": preempt_near,
                    },
                }
            )
        delay = risk_metrics.get("detectionDelayFrames", {})
        delay_max = int(delay.get("max", 0) or 0) if isinstance(delay, dict) else 0
        if delay_max >= 2:
            findings.append(
                {
                    "severity": "warning",
                    "type": "high_risk_delay",
                    "frameSeq": None,
                    "message": f"risk detection delay max={delay_max} frames",
                    "evidence": {"detectionDelayFrames": delay},
                }
            )
        normalization = risk_metrics.get("normalization", {})
        if isinstance(normalization, dict):
            unknown = normalization.get("unknownKinds", [])
            if isinstance(unknown, list) and unknown:
                findings.append(
                    {
                        "severity": "info",
                        "type": "unknown_hazard_kind",
                        "frameSeq": None,
                        "message": f"unknown hazard kinds detected: {', '.join(str(x) for x in unknown)}",
                        "evidence": {"unknownKinds": unknown},
                    }
                )

    if isinstance(ocr_metrics, dict):
        mismatches = ocr_metrics.get("topMismatches", [])
        if isinstance(mismatches, list) and mismatches:
            item = mismatches[0]
            findings.append(
                {
                    "severity": "info",
                    "type": "ocr_top_mismatch",
                    "frameSeq": item.get("frameSeq"),
                    "message": "ocr mismatch observed",
                    "evidence": item,
                }
            )

    return findings[:8]


def _resolve_ground_truth(run_package_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    default_ocr_rel = "ground_truth/ocr.jsonl"
    default_risk_rel = "ground_truth/depth_risk.jsonl"
    gt_raw = manifest.get("groundTruth")
    gt_cfg = gt_raw if isinstance(gt_raw, dict) else {}

    ocr_rel = str(gt_cfg.get("ocrJsonl", "")).strip()
    risk_rel = str(gt_cfg.get("riskJsonl", "")).strip()
    if not ocr_rel and (run_package_dir / default_ocr_rel).exists():
        ocr_rel = default_ocr_rel
    if not risk_rel and (run_package_dir / default_risk_rel).exists():
        risk_rel = default_risk_rel

    ocr_path = run_package_dir / ocr_rel if ocr_rel else None
    risk_path = run_package_dir / risk_rel if risk_rel else None
    if ocr_path is not None and not ocr_path.exists():
        ocr_path = None
    if risk_path is not None and not risk_path.exists():
        risk_path = None

    raw_window = gt_cfg.get("matchWindowFrames", 2)
    try:
        window = int(raw_window)
    except (TypeError, ValueError):
        window = 2
    window = max(0, window)

    return {
        "hasGroundTruth": bool(ocr_path or risk_path),
        "ocrPath": str(ocr_path) if ocr_path is not None else "",
        "riskPath": str(risk_path) if risk_path is not None else "",
        "matchWindowFrames": window,
    }


def load_run_package(run_package_dir: Path) -> tuple[Path, Path | None, Path | None, dict[str, Any]]:
    manifest_path = run_package_dir / "manifest.json"
    if not manifest_path.exists():
        manifest_path = run_package_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found in run package: {run_package_dir}")

    manifest_raw = json.loads(load_text(manifest_path))
    if not isinstance(manifest_raw, dict):
        raise ValueError("run package manifest must be an object")
    manifest = manifest_raw

    events_v1_relative = str(manifest.get("eventsV1Jsonl", "")).strip()
    events_v1_path: Path | None = None
    event_schema_warnings: list[str] = []
    if events_v1_relative:
        candidate = run_package_dir / events_v1_relative
        if candidate.exists():
            events_v1_path = candidate
        else:
            legacy_candidate = run_package_dir / "events_v1.jsonl"
            if legacy_candidate.exists():
                events_v1_path = legacy_candidate
                event_schema_warnings.append(
                    f"eventsV1Jsonl missing at {events_v1_relative}; fallback to events_v1.jsonl"
                )
    if events_v1_path is None:
        autodetect_rel = "events/events_v1.jsonl"
        autodetect_candidate = run_package_dir / autodetect_rel
        if autodetect_candidate.exists():
            events_v1_path = autodetect_candidate
            if not events_v1_relative:
                events_v1_relative = autodetect_rel

    ws_relative = str(manifest.get("wsJsonl", "")).strip() or "ws_events.jsonl"
    ws_jsonl = run_package_dir / ws_relative
    if not ws_jsonl.exists():
        fallback_ui_events = run_package_dir / "ui_events.jsonl"
        if fallback_ui_events.exists():
            ws_jsonl = fallback_ui_events
        elif events_v1_path is not None:
            ws_jsonl = events_v1_path
        else:
            raise FileNotFoundError(f"ws jsonl not found: {ws_jsonl}")

    event_source_path = events_v1_path if events_v1_path is not None else ws_jsonl
    event_source = "eventsV1Jsonl" if events_v1_path is not None else "wsEventsJsonl"

    metrics_before_path: Path | None = None
    metrics_after_path: Path | None = None
    before_relative = str(manifest.get("metricsBefore", "")).strip()
    after_relative = str(manifest.get("metricsAfter", "")).strip()
    if before_relative:
        candidate = run_package_dir / before_relative
        if candidate.exists():
            metrics_before_path = candidate
    if after_relative:
        candidate = run_package_dir / after_relative
        if candidate.exists():
            metrics_after_path = candidate

    summary = {
        "runPackageDir": str(run_package_dir),
        "scenarioTag": manifest.get("scenarioTag", ""),
        "startMs": manifest.get("startMs", ""),
        "endMs": manifest.get("endMs", ""),
        "frameCountSent": manifest.get("frameCountSent", ""),
        "eventCountAccepted": manifest.get("eventCountAccepted", ""),
        "localSafetyFallbackEnterCount": manifest.get("localSafetyFallbackEnterCount", ""),
        "healthStatusCounts": manifest.get("healthStatusCounts", {}),
        "errors": manifest.get("errors", []),
        "groundTruth": _resolve_ground_truth(run_package_dir, manifest),
        "eventSchemaSource": event_source,
        "eventSchemaInputPath": str(event_source_path),
        "eventsV1Path": events_v1_relative if events_v1_path is not None else "",
        "eventSchemaWarnings": event_schema_warnings,
    }

    return ws_jsonl, metrics_before_path, metrics_after_path, summary


def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_name = member.filename.replace("\\", "/")
            if member_name.startswith("/") or member_name.startswith("../") or "/../" in member_name:
                raise ValueError(f"unsafe zip entry: {member.filename}")
            resolved = (target_dir / member.filename).resolve()
            if not str(resolved).startswith(str(target_dir.resolve())):
                raise ValueError(f"zip path traversal detected: {member.filename}")
        zf.extractall(target_dir)


def resolve_run_package_input(run_package_path: Path) -> tuple[Path, Path | None, Path | None, dict[str, Any], Path | None]:
    if run_package_path.is_dir():
        ws_jsonl, before, after, summary = load_run_package(run_package_path)
        return ws_jsonl, before, after, summary, None

    if run_package_path.is_file() and run_package_path.suffix.lower() == ".zip":
        extract_root = Path(tempfile.mkdtemp(prefix="runpkg_extract_"))
        try:
            safe_extract_zip(run_package_path, extract_root)
            ws_jsonl, before, after, summary = load_run_package(extract_root)
            summary["sourceZip"] = str(run_package_path)
            return ws_jsonl, before, after, summary, extract_root
        except Exception:
            shutil.rmtree(extract_root, ignore_errors=True)
            raise

    raise FileNotFoundError(f"run package path not supported: {run_package_path}")


def generate_report(
    *,
    ws_jsonl: Path,
    output: Path,
    metrics_url: str,
    metrics_before_path: Path | None,
    metrics_after_path: Path | None,
    external_readiness_url: str | None,
    run_package_summary: dict[str, Any] | None,
) -> Path:
    report_path, _json_path, _summary = generate_report_outputs(
        ws_jsonl=ws_jsonl,
        output=output,
        metrics_url=metrics_url,
        metrics_before_path=metrics_before_path,
        metrics_after_path=metrics_after_path,
        external_readiness_url=external_readiness_url,
        run_package_summary=run_package_summary,
        output_json=None,
    )
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate markdown report from metrics + ws jsonl")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8000/metrics")
    parser.add_argument("--metrics-before", default=None)
    parser.add_argument("--metrics-after", default=None)
    parser.add_argument("--external-readiness-url", default=None)
    parser.add_argument("--ws-jsonl", default=None)
    parser.add_argument("--run-package", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args()

    run_package_dir: Path | None = None
    run_package_source: Path | None = None
    run_package_is_zip = False
    cleanup_dir: Path | None = None
    run_package_summary: dict[str, Any] | None = None

    try:
        if args.run_package:
            run_package_source = Path(args.run_package)
            if not run_package_source.exists():
                print(f"run package path not found: {run_package_source}")
                return 1
            run_package_is_zip = run_package_source.is_file() and run_package_source.suffix.lower() == ".zip"
            ws_jsonl, pkg_before, pkg_after, run_package_summary, cleanup_dir = resolve_run_package_input(run_package_source)
            run_package_dir = None if run_package_is_zip else run_package_source
        else:
            if not args.ws_jsonl:
                print("either --ws-jsonl or --run-package is required")
                return 1
            ws_jsonl = Path(args.ws_jsonl)
            pkg_before = None
            pkg_after = None
            if not ws_jsonl.exists():
                print(f"ws jsonl not found: {ws_jsonl}")
                return 1

        metrics_before_path = Path(args.metrics_before) if args.metrics_before else pkg_before
        metrics_after_path = Path(args.metrics_after) if args.metrics_after else pkg_after

        if (metrics_before_path is None) != (metrics_after_path is None):
            print("must provide both --metrics-before and --metrics-after, or neither")
            return 1

        if args.output:
            output = Path(args.output)
        elif run_package_is_zip and run_package_source is not None:
            output = run_package_source.parent / f"report_{run_package_source.stem}.md"
        else:
            output = derive_output_path(ws_jsonl, args.output, run_package_dir)

        output_json = Path(args.output_json) if args.output_json else None
        output, json_path, _summary = generate_report_outputs(
            ws_jsonl=ws_jsonl,
            output=output,
            metrics_url=args.metrics_url,
            metrics_before_path=metrics_before_path,
            metrics_after_path=metrics_after_path,
            external_readiness_url=args.external_readiness_url,
            run_package_summary=run_package_summary,
            output_json=output_json,
        )
        print(f"report generated -> {output}")
        if json_path is not None:
            print(f"summary generated -> {json_path}")
        return 0
    except Exception as ex:
        print(str(ex))
        return 1
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def _derive_external_readiness_url(metrics_url: str) -> str:
    parsed = urlparse(str(metrics_url).strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, "/api/external_readiness", "", "", ""))


if __name__ == "__main__":
    sys.exit(main())
