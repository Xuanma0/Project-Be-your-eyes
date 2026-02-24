from __future__ import annotations

from typing import Any


def compute_pov_plan_metrics(pov_ir: dict[str, Any] | None, plan_summary: dict[str, Any] | None) -> dict[str, Any]:
    pov_payload = pov_ir if isinstance(pov_ir, dict) else None
    plan_payload = plan_summary if isinstance(plan_summary, dict) else None
    if not pov_payload or not plan_payload or not bool(plan_payload.get("present")):
        return {
            "present": False,
            "decisionCoverage": 0.0,
            "actionCoverage": 0.0,
            "consistencyWarnings": 0,
            "warnings": [],
        }

    decisions = pov_payload.get("decisionPoints")
    decisions = [row for row in decisions if isinstance(row, dict)] if isinstance(decisions, list) else []
    decision_ids = {str(row.get("id", "")).strip() for row in decisions if str(row.get("id", "")).strip()}

    actions = plan_payload.get("actions")
    actions = actions if isinstance(actions, dict) else {}
    action_count = int(actions.get("count", 0) or 0)

    mapped_decision_ids = _extract_mapped_decision_ids(plan_payload)
    mapped_decision_count = len(mapped_decision_ids & decision_ids)

    decision_coverage = round(float(mapped_decision_count) / float(max(1, len(decision_ids))), 4)

    actions_with_trace = _count_actions_with_trace(plan_payload)
    action_coverage = round(float(actions_with_trace) / float(max(1, action_count)), 4)

    warnings: list[str] = []
    unknown_ids = sorted(mapped_decision_ids - decision_ids)
    if unknown_ids:
        warnings.append(f"unknown_sourceDecisionIds:{','.join(unknown_ids[:5])}")
    if decision_ids and decision_coverage < 0.5:
        warnings.append(f"low_decision_coverage:{decision_coverage}")
    if action_count > 0 and action_coverage < 0.5:
        warnings.append(f"low_action_coverage:{action_coverage}")

    return {
        "present": True,
        "decisionCoverage": decision_coverage,
        "actionCoverage": action_coverage,
        "consistencyWarnings": len(warnings),
        "warnings": warnings,
    }


def _extract_mapped_decision_ids(plan_summary: dict[str, Any]) -> set[str]:
    mapped: set[str] = set()
    action_details = plan_summary.get("actionDetails")
    rows = action_details if isinstance(action_details, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        ids = payload.get("sourceDecisionIds")
        ids = ids if isinstance(ids, list) else []
        for item in ids:
            text = str(item).strip()
            if text:
                mapped.add(text)
    return mapped


def _count_actions_with_trace(plan_summary: dict[str, Any]) -> int:
    total = 0
    action_details = plan_summary.get("actionDetails")
    rows = action_details if isinstance(action_details, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        source = str(payload.get("source", "")).strip().lower()
        ids = payload.get("sourceDecisionIds")
        ids = ids if isinstance(ids, list) else []
        has_ids = any(str(item).strip() for item in ids)
        if source == "pov" or has_ids:
            total += 1
    return total
