from __future__ import annotations

from copy import deepcopy
from typing import Any


def classify_risk_level(hazards: list[dict[str, Any]]) -> str:
    if not isinstance(hazards, list) or not hazards:
        return "low"
    level = "low"
    for item in hazards:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "")).strip().lower()
        if severity == "critical":
            return "critical"
        if severity in {"high", "severe"}:
            level = "high"
        elif severity in {"warning", "warn"} and level not in {"high", "critical"}:
            level = "medium"
    return level


def apply_guardrails(
    plan: dict[str, Any],
    risk_level: str,
    constraints: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    constraints = constraints if isinstance(constraints, dict) else {}
    out = deepcopy(plan if isinstance(plan, dict) else {})
    actions = out.get("actions")
    if not isinstance(actions, list):
        actions = []
    safe_actions = [dict(item) for item in actions if isinstance(item, dict)]
    guardrails: list[str] = []
    findings: list[dict[str, Any]] = []

    ttl_ms = _as_int(out.get("ttlMs"))
    if ttl_ms is None or ttl_ms <= 0:
        old = out.get("ttlMs")
        out["ttlMs"] = 2000
        guardrails.append("default_ttl_applied")
        findings.append({"type": "ttl", "reason": "missing_or_invalid", "before": old, "after": 2000})

    normalized_risk = str(risk_level or "").strip().lower()
    if normalized_risk not in {"low", "medium", "high", "critical"}:
        normalized_risk = "low"

    if normalized_risk == "critical":
        has_stop = any(str(item.get("type", "")).strip().lower() == "stop" for item in safe_actions)
        if not has_stop:
            safe_actions.insert(
                0,
                {
                    "type": "stop",
                    "priority": 0,
                    "payload": {"reason": "critical_risk_guardrail"},
                    "requiresConfirm": False,
                    "blocking": True,
                },
            )
            guardrails.append("critical_inject_stop")
            findings.append({"type": "inject_stop", "reason": "critical_risk"})
        for idx, action in enumerate(safe_actions):
            action_type = str(action.get("type", "")).strip().lower()
            if action_type in {"stop", "confirm"}:
                continue
            if bool(action.get("requiresConfirm")):
                continue
            before = action.get("requiresConfirm")
            action["requiresConfirm"] = True
            guardrails.append("critical_force_requires_confirm")
            findings.append(
                {
                    "type": "requires_confirm",
                    "reason": "critical_risk",
                    "index": idx,
                    "actionType": action_type,
                    "before": before,
                    "after": True,
                }
            )
    elif normalized_risk == "high":
        for idx, action in enumerate(safe_actions):
            if bool(action.get("requiresConfirm")):
                continue
            before = action.get("requiresConfirm")
            action["requiresConfirm"] = True
            guardrails.append("high_force_requires_confirm")
            findings.append(
                {
                    "type": "requires_confirm",
                    "reason": "high_risk",
                    "index": idx,
                    "actionType": str(action.get("type", "")).strip().lower(),
                    "before": before,
                    "after": True,
                }
            )

    max_actions = _as_int(constraints.get("maxActions"))
    if max_actions is None or max_actions <= 0:
        max_actions = 3
    if len(safe_actions) > max_actions:
        before = len(safe_actions)
        safe_actions = sorted(
            safe_actions,
            key=lambda item: (_priority_value(item), str(item.get("type", ""))),
        )[:max_actions]
        guardrails.append("max_actions_trimmed")
        findings.append({"type": "trim_actions", "reason": "maxActions", "beforeCount": before, "afterCount": len(safe_actions)})

    out["actions"] = safe_actions
    meta = out.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    safety_meta = meta.get("safety")
    safety_meta = safety_meta if isinstance(safety_meta, dict) else {}
    safety_meta["guardrailsApplied"] = sorted(set(guardrails))
    if findings:
        safety_meta["notes"] = f"findings={len(findings)}"
    meta["safety"] = safety_meta
    out["meta"] = meta
    return out, sorted(set(guardrails)), findings


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _priority_value(action: dict[str, Any]) -> int:
    parsed = _as_int(action.get("priority"))
    if parsed is None:
        return 9999
    return parsed
