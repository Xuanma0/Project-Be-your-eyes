from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

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
        if normalized in {"NORMAL", "DEGRADED", "SAFE_MODE", "WAITING_CLIENT"}:
            return normalized

    summary = str(event.get("summary", ""))
    status = str(event.get("status", ""))

    payload = event.get("payload")
    if isinstance(payload, dict):
        payload_health_status = payload.get("healthStatus")
        if isinstance(payload_health_status, str):
            normalized = payload_health_status.strip().upper()
            if normalized in {"NORMAL", "DEGRADED", "SAFE_MODE", "WAITING_CLIENT"}:
                return normalized
        payload_status = payload.get("status")
        if isinstance(payload_status, str) and payload_status:
            status = payload_status

    text = " ".join([summary, status]).strip().lower()
    if "safe_mode" in text:
        return "SAFE_MODE"
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
    expired_emitted = 0
    first_safe_mode_ms: int | None = None
    safe_mode_active = False
    perception_after_safe_mode = 0
    action_plan_after_safe_mode = 0
    active_confirm_events = 0
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
        "active_confirm_events": active_confirm_events,
        "hazard_events": hazard_events,
        "unique_hazards": len(unique_hazard_ids),
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
) -> str:
    lines: list[str] = []
    lines.append(f"# {markdown_title}")
    lines.append("")
    lines.append("## Inputs")
    lines.append(f"- ws jsonl: `{ws_jsonl}`")
    lines.append(f"- metrics source: `{metrics_source}`")
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
    lines.append(f"- active_confirm_events: `{ws_stats['active_confirm_events']}`")
    lines.append(f"- hazard_events: `{ws_stats['hazard_events']}`")
    lines.append(f"- unique_hazards: `{ws_stats['unique_hazards']}`")
    lines.append(f"- action-plan events: `{ws_stats['event_types'].get('action_plan', 0)}`")
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
        "byes_tool_cache_hit_total",
        "byes_tool_cache_miss_total",
        "byes_tool_rate_limited_total",
        "byes_frame_gate_skip_total",
        "byes_safemode_enter_total",
        "byes_deadline_miss_total",
        "byes_backpressure_drop_total",
        "byes_fault_set_total",
        "byes_fault_trigger_total",
        "byes_health_warn_total",
        "byes_crosscheck_conflict_total",
        "byes_active_confirm_total",
        "byes_actionplan_patched_total",
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
    append_metric_details(lines, after_samples, "byes_tool_cache_hit_total", ["tool"], "count")
    append_metric_details(lines, after_samples, "byes_tool_cache_miss_total", ["tool"], "count")
    append_metric_details(lines, after_samples, "byes_tool_rate_limited_total", ["tool"], "count")
    append_metric_details(lines, after_samples, "byes_frame_gate_skip_total", ["tool", "reason"], "count")
    append_metric_details(lines, after_samples, "byes_crosscheck_conflict_total", ["kind"], "count")
    append_metric_details(lines, after_samples, "byes_active_confirm_total", ["kind"], "count")
    append_metric_details(lines, after_samples, "byes_actionplan_patched_total", ["reason"], "count")
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
            "byes_tool_cache_hit_total",
            "byes_tool_cache_miss_total",
            "byes_tool_rate_limited_total",
            "byes_frame_gate_skip_total",
            "byes_safemode_enter_total",
            "byes_deadline_miss_total",
            "byes_backpressure_drop_total",
            "byes_fault_set_total",
            "byes_fault_trigger_total",
            "byes_health_warn_total",
            "byes_crosscheck_conflict_total",
            "byes_active_confirm_total",
            "byes_actionplan_patched_total",
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
        append_metric_details(lines, delta_samples, "byes_tool_cache_hit_total", ["tool"], "delta")
        append_metric_details(lines, delta_samples, "byes_tool_cache_miss_total", ["tool"], "delta")
        append_metric_details(lines, delta_samples, "byes_tool_rate_limited_total", ["tool"], "delta")
        append_metric_details(lines, delta_samples, "byes_frame_gate_skip_total", ["tool", "reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_crosscheck_conflict_total", ["kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_active_confirm_total", ["kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_actionplan_patched_total", ["reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_hazard_emit_total", ["kind"], "delta")
        append_metric_details(lines, delta_samples, "byes_hazard_suppressed_total", ["reason"], "delta")
        append_metric_details(lines, delta_samples, "byes_hazard_persist_total", ["kind"], "delta")
        _append_tool_focus(lines, delta_samples, tool="real_det", delta=True)
        _append_tool_focus(lines, delta_samples, tool="real_ocr", delta=True)
        _append_tool_focus(lines, delta_samples, tool="real_depth", delta=True)
        _append_tool_focus(lines, delta_samples, tool="real_vlm", delta=True)

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


def derive_output_path(ws_jsonl: Path, output: str | None) -> Path:
    if output:
        return Path(output)
    return Path(f"report_{ws_jsonl.stem}.md")


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate markdown report from metrics + ws jsonl")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8000/metrics")
    parser.add_argument("--metrics-before", default=None)
    parser.add_argument("--metrics-after", default=None)
    parser.add_argument("--ws-jsonl", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    ws_jsonl = Path(args.ws_jsonl)
    if not ws_jsonl.exists():
        print(f"ws jsonl not found: {ws_jsonl}")
        return 1

    metrics_before_path = Path(args.metrics_before) if args.metrics_before else None
    metrics_after_path = Path(args.metrics_after) if args.metrics_after else None

    if (metrics_before_path is None) != (metrics_after_path is None):
        print("must provide both --metrics-before and --metrics-after, or neither")
        return 1

    output = derive_output_path(ws_jsonl, args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    ws_rows = load_jsonl(ws_jsonl)
    ws_stats = collect_ws_stats(ws_rows)

    if metrics_before_path is not None and metrics_after_path is not None:
        if not metrics_before_path.exists():
            print(f"metrics before file not found: {metrics_before_path}")
            return 1
        if not metrics_after_path.exists():
            print(f"metrics after file not found: {metrics_after_path}")
            return 1

        before_text = load_text(metrics_before_path)
        after_text = load_text(metrics_after_path)
        metrics_source = f"before={metrics_before_path}, after={metrics_after_path}"
    else:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(args.metrics_url)
            response.raise_for_status()
            after_text = response.text
        before_text = ""
        metrics_source = args.metrics_url

    after_samples = parse_prometheus_text_to_map(after_text)
    delta_samples = None
    if before_text:
        before_samples = parse_prometheus_text_to_map(before_text)
        delta_samples = compute_delta(before_samples, after_samples)

    report_title = f"Run Report - {ws_jsonl.stem}"
    report_text = build_report(
        report_title,
        ws_jsonl,
        metrics_source,
        ws_stats,
        after_samples,
        delta_samples,
    )
    output.write_text(report_text + "\n", encoding="utf-8")
    print(f"report generated -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
