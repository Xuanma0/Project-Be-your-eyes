from __future__ import annotations

from typing import Any, Iterable

from byes.latency_stats import summarize_latency


def compute_plan_eval(events: Iterable[dict[str, Any]] | None, report: dict[str, Any] | None) -> dict[str, Any]:
    normalized_events = _normalize_events(events)
    report_payload = report if isinstance(report, dict) else {}
    plan_payload = report_payload.get("plan")
    plan_payload = plan_payload if isinstance(plan_payload, dict) else {}
    plan_actions = plan_payload.get("actions")
    plan_actions = plan_actions if isinstance(plan_actions, dict) else {}

    present = bool(plan_payload.get("present")) or any(
        str(event.get("name", "")).strip().lower() in {"plan.generate", "plan.execute"}
        for event in normalized_events
    )

    plan_generate_latencies: list[int] = []
    execute_latencies: list[int] = []
    confirm_requests = 0
    confirm_responses = 0
    explicit_confirm_timeouts = 0
    pending_confirm_values: list[int] = []
    risk_levels: list[str] = []
    rule_applied_count = 0
    rule_hints: list[str] = []

    request_ids: set[str] = set()
    response_ids: set[str] = set()

    for event in normalized_events:
        name = str(event.get("name", "")).strip().lower()
        phase = str(event.get("phase", "")).strip().lower()
        status = str(event.get("status", "")).strip().lower()
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}

        if name == "plan.generate" and phase == "result" and status == "ok":
            latency = _to_int(event.get("latencyMs"))
            if latency is not None and latency >= 0:
                plan_generate_latencies.append(latency)
            risk_level = str(payload.get("riskLevel", "")).strip().lower()
            if risk_level:
                risk_levels.append(risk_level)

        if name == "plan.execute" and phase == "result" and status == "ok":
            latency = _to_int(event.get("latencyMs"))
            if latency is not None and latency >= 0:
                execute_latencies.append(latency)
            pending = _to_int(payload.get("pendingConfirmCount"))
            if pending is not None and pending >= 0:
                pending_confirm_values.append(pending)

        if name == "ui.confirm_request":
            confirm_requests += 1
            confirm_id = str(payload.get("confirmId", "")).strip()
            if confirm_id:
                request_ids.add(confirm_id)

        if name == "ui.confirm_response":
            confirm_responses += 1
            confirm_id = str(payload.get("confirmId", "")).strip()
            if confirm_id:
                response_ids.add(confirm_id)

        if name in {"ui.confirm_timeout", "safety.confirm"}:
            timeout_hit = name == "ui.confirm_timeout"
            if not timeout_hit:
                timeout_hit = status == "timeout" or phase == "timeout"
                if not timeout_hit:
                    reason = str(payload.get("reason", "")).strip().lower()
                    timeout_hit = "timeout" in reason or "expired" in reason
            if timeout_hit:
                explicit_confirm_timeouts += 1

        if name == "plan.rule_applied" and phase == "result" and status == "ok":
            rule_applied_count += 1
            hint = str(payload.get("hazardHint", "")).strip().lower()
            if hint:
                rule_hints.append(hint)

    unmatched_by_id = 0
    if request_ids:
        unmatched_by_id = len(request_ids - response_ids)

    implied_pending = max(0, confirm_requests - confirm_responses)
    pending_confirm = max(implied_pending, unmatched_by_id)
    if pending_confirm_values:
        pending_confirm = max(pending_confirm, max(pending_confirm_values))

    confirm_timeouts = max(explicit_confirm_timeouts, pending_confirm)

    actions_count = _to_int(plan_actions.get("count")) or 0
    stop_count = _to_int(plan_actions.get("stopCount"))
    if stop_count is None:
        stop_count = _count_action_type(plan_actions.get("types"), "stop")
    confirm_action_count = _to_int(plan_actions.get("confirmActionCount"))
    if confirm_action_count is None:
        confirm_action_count = _count_action_type(plan_actions.get("types"), "confirm")
    blocking_count = _to_int(plan_actions.get("blockingCount"))
    if blocking_count is None:
        blocking_count = stop_count + confirm_action_count

    if actions_count <= 0:
        actions_count = max(stop_count + confirm_action_count, _to_int(plan_actions.get("requiresConfirmCount")) or 0)

    guardrails = plan_payload.get("guardrailsApplied")
    guardrails = [str(item).strip() for item in guardrails] if isinstance(guardrails, list) else []
    guardrails = [item for item in guardrails if item]
    guardrails_applied_count = len(guardrails)
    guardrail_override_rate = round(float(guardrails_applied_count) / float(max(1, actions_count)), 4)

    risk_level = _pick_risk_level(plan_payload, risk_levels)
    stop_when_not_critical = stop_count if risk_level != "critical" else 0
    confirm_when_not_critical = confirm_action_count if risk_level != "critical" else 0
    overcautious_rate = round(
        float(stop_when_not_critical + confirm_when_not_critical) / float(max(1, actions_count)),
        4,
    )

    return {
        "present": bool(present),
        "latencyMs": summarize_latency(plan_generate_latencies),
        "executeLatencyMs": summarize_latency(execute_latencies),
        "confirm": {
            "requests": int(confirm_requests),
            "responses": int(confirm_responses),
            "timeouts": int(confirm_timeouts),
            "pending": int(pending_confirm),
        },
        "actions": {
            "count": int(max(0, actions_count)),
            "stopCount": int(max(0, stop_count)),
            "blockingCount": int(max(0, blocking_count)),
            "confirmActionCount": int(max(0, confirm_action_count)),
        },
        "guardrails": {
            "appliedCount": int(guardrails_applied_count),
            "overrideRate": guardrail_override_rate,
        },
        "overcautious": {
            "rate": overcautious_rate,
            "stopWhenNotCritical": int(max(0, stop_when_not_critical)),
            "confirmWhenNotCritical": int(max(0, confirm_when_not_critical)),
        },
        "ruleAppliedCount": int(rule_applied_count),
        "ruleHazardHintTop": _most_common_text(rule_hints),
    }


def _normalize_events(events: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if events is None:
        return rows
    for row in events:
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if isinstance(event, dict):
            rows.append(event)
    return rows


def _to_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _count_action_type(action_types: Any, expected: str) -> int:
    if not isinstance(action_types, list):
        return 0
    normalized = str(expected).strip().lower()
    total = 0
    for item in action_types:
        if str(item).strip().lower() == normalized:
            total += 1
    return total


def _pick_risk_level(plan_payload: dict[str, Any], risk_levels: list[str]) -> str:
    level = str(plan_payload.get("riskLevel", "")).strip().lower()
    if level:
        return level
    if risk_levels:
        return risk_levels[-1]
    return "low"


def _most_common_text(values: list[str]) -> str | None:
    if not values:
        return None
    counts: dict[str, int] = {}
    for item in values:
        key = str(item).strip().lower()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
