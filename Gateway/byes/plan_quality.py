from __future__ import annotations

from typing import Any


def compute_plan_quality(plan_summary: dict[str, Any] | None) -> dict[str, Any]:
    plan = plan_summary if isinstance(plan_summary, dict) else {}
    present = bool(plan.get("present"))
    risk_level = str(plan.get("riskLevel", "")).strip().lower() or "low"
    actions_payload = plan.get("actions")
    actions_payload = actions_payload if isinstance(actions_payload, dict) else {}
    action_types = actions_payload.get("types")
    action_types = [str(item).strip().lower() for item in action_types] if isinstance(action_types, list) else []
    actions_count = int(actions_payload.get("count", 0) or 0)
    guardrails = plan.get("guardrailsApplied")
    guardrails = [str(item).strip() for item in guardrails] if isinstance(guardrails, list) else []
    guardrails = [item for item in guardrails if item]
    guardrails_count = len(guardrails)
    planner = plan.get("planner")
    planner = planner if isinstance(planner, dict) else {}
    fallback_used = bool(planner.get("fallbackUsed")) if "fallbackUsed" in planner else False
    fallback_reason_raw = planner.get("fallbackReason")
    fallback_reason = None if fallback_reason_raw is None else (str(fallback_reason_raw).strip() or None)
    json_valid_raw = planner.get("jsonValid")
    json_valid = bool(json_valid_raw) if isinstance(json_valid_raw, bool) else None
    prompt_version = str(planner.get("promptVersion", "")).strip() or None
    seg_context_included = bool(plan.get("segContextIncluded")) if "segContextIncluded" in plan else False
    try:
        seg_context_chars = max(0, int(plan.get("segContextChars", 0) or 0))
    except Exception:
        seg_context_chars = 0
    try:
        seg_context_trunc_dropped = max(0, int(plan.get("segContextTruncSegmentsDropped", 0) or 0))
    except Exception:
        seg_context_trunc_dropped = 0
    has_stop = "stop" in action_types
    has_confirm = "confirm" in action_types
    guardrail_rate = round(float(guardrails_count) / float(max(1, actions_count)), 4)

    critical_requires_stop = True
    critical_requires_confirm = True
    if risk_level == "critical":
        critical_requires_stop = has_stop
        critical_requires_confirm = has_confirm

    if not present:
        score = 0.0
    else:
        score = 100.0
        if actions_count <= 0:
            score -= 20.0
        if risk_level == "critical":
            if not has_stop:
                score -= 40.0
            if not has_confirm:
                score -= 30.0
        elif risk_level == "high":
            if not has_confirm:
                score -= 15.0
        if score < 0:
            score = 0.0
    score = round(score, 2)

    return {
        "present": present,
        "riskLevel": risk_level,
        "actionsCount": actions_count,
        "hasStop": has_stop,
        "hasConfirm": has_confirm,
        "guardrailsAppliedCount": guardrails_count,
        "guardrailRate": guardrail_rate,
        "consistency": {
            "critical_requires_stop": critical_requires_stop,
            "critical_requires_confirm": critical_requires_confirm,
        },
        "fallbackUsed": fallback_used,
        "fallbackReason": fallback_reason,
        "jsonValid": json_valid,
        "promptVersion": prompt_version,
        "segContextIncluded": seg_context_included,
        "segContextChars": seg_context_chars,
        "segContextTruncSegmentsDropped": seg_context_trunc_dropped,
        "score": score,
    }
