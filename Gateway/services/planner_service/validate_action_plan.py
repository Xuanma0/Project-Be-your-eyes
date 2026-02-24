from __future__ import annotations

from copy import deepcopy
from typing import Any

_ALLOWED_TYPES = {"speak", "overlay", "haptic", "confirm", "stop"}


def validate_and_normalize(plan: Any, constraints: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "jsonValid": False,
        "errors": [],
        "actionsTrimmed": 0,
    }
    if not isinstance(plan, dict):
        diagnostics["errors"].append("plan_not_object")
        return None, diagnostics
    if str(plan.get("schemaVersion", "")).strip() != "byes.action_plan.v1":
        diagnostics["errors"].append("schema_version_invalid")
        return None, diagnostics

    normalized = deepcopy(plan)
    actions = normalized.get("actions")
    if not isinstance(actions, list):
        diagnostics["errors"].append("actions_not_list")
        return None, diagnostics

    valid_actions: list[dict[str, Any]] = []
    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            diagnostics["errors"].append(f"action_{idx}_not_object")
            continue
        action_type = str(action.get("type", "")).strip().lower()
        if action_type not in _ALLOWED_TYPES:
            diagnostics["errors"].append(f"action_{idx}_type_invalid")
            continue
        priority = _as_int(action.get("priority"))
        if priority is None:
            diagnostics["errors"].append(f"action_{idx}_priority_invalid")
            continue
        payload = action.get("payload")
        if not isinstance(payload, dict):
            diagnostics["errors"].append(f"action_{idx}_payload_invalid")
            continue
        requires_confirm = action.get("requiresConfirm")
        blocking = action.get("blocking")
        if not isinstance(requires_confirm, bool):
            diagnostics["errors"].append(f"action_{idx}_requiresConfirm_invalid")
            continue
        if not isinstance(blocking, bool):
            diagnostics["errors"].append(f"action_{idx}_blocking_invalid")
            continue

        valid_actions.append(
            {
                "type": action_type,
                "priority": priority,
                "payload": payload,
                "requiresConfirm": requires_confirm,
                "blocking": blocking,
            }
        )

    if not valid_actions:
        diagnostics["errors"].append("no_valid_actions")
        return None, diagnostics

    max_actions = 3
    if isinstance(constraints, dict):
        parsed = _as_int(constraints.get("maxActions"))
        if parsed is not None and parsed > 0:
            max_actions = parsed
    ordered_actions = sorted(valid_actions, key=lambda item: _priority_value(item))
    trimmed = max(0, len(ordered_actions) - max_actions)
    if trimmed > 0:
        ordered_actions = ordered_actions[:max_actions]
        diagnostics["actionsTrimmed"] = trimmed

    normalized["actions"] = ordered_actions
    diagnostics["jsonValid"] = True
    return normalized, diagnostics


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
