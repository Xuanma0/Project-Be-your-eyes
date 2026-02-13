from __future__ import annotations

from typing import Any, Callable


UiEmitFn = Callable[[dict[str, Any]], None]
NowMsFn = Callable[[], int]


def execute_plan(
    plan: dict[str, Any],
    emit_event_fn: UiEmitFn,
    now_ms_fn: NowMsFn,
) -> dict[str, Any]:
    actions_raw = plan.get("actions")
    actions_raw = actions_raw if isinstance(actions_raw, list) else []
    indexed_actions = [
        (idx, dict(action))
        for idx, action in enumerate(actions_raw)
        if isinstance(action, dict)
    ]
    ordered = sorted(
        indexed_actions,
        key=lambda pair: (_as_int(pair[1].get("priority"), 9999), pair[0]),
    )

    executed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    pending_confirms: list[dict[str, Any]] = []
    ui_commands: list[dict[str, Any]] = []

    blocking_priority: int | None = None
    for default_index, action in ordered:
        action_type = str(action.get("type", "")).strip().lower()
        priority = _as_int(action.get("priority"), 9999)
        action_id = _resolve_action_id(action, default_index + 1)
        payload = action.get("payload")
        payload = payload if isinstance(payload, dict) else {}

        if _is_blocked_by_previous(blocking_priority, priority, action_type):
            blocked_item = {
                "type": action_type or "unknown",
                "actionId": action_id,
                "reason": "blocked_by_previous_blocking_action",
            }
            blocked.append(blocked_item)
            continue

        if action_type == "confirm":
            confirm_id = str(payload.get("confirmId", "")).strip() or f"confirm-{action_id}"
            timeout_ms = _as_int(payload.get("timeoutMs"), 5000)
            text = str(payload.get("text", "")).strip() or "Please confirm."
            command = {
                "kind": "ui.confirm_request",
                "actionId": action_id,
                "confirmId": confirm_id,
                "text": text,
                "timeoutMs": timeout_ms,
                "tsMs": int(max(0, now_ms_fn())),
            }
            ui_commands.append(command)
            pending_confirms.append(
                {
                    "confirmId": confirm_id,
                    "timeoutMs": timeout_ms,
                    "actionId": action_id,
                }
            )
            executed.append({"type": action_type, "actionId": action_id})
            emit_event_fn(command)
        elif action_type in {"speak", "overlay", "haptic", "stop"}:
            command = {
                "kind": "ui.command",
                "commandType": action_type,
                "actionId": action_id,
                "text": str(payload.get("text", "")).strip() if payload.get("text") is not None else "",
                "label": str(payload.get("label", "")).strip() if payload.get("label") is not None else "",
                "reason": str(payload.get("reason", "")).strip() if payload.get("reason") is not None else "",
                "tsMs": int(max(0, now_ms_fn())),
            }
            ui_commands.append(command)
            executed.append({"type": action_type, "actionId": action_id})
            emit_event_fn(command)
        else:
            blocked.append(
                {
                    "type": action_type or "unknown",
                    "actionId": action_id,
                    "reason": "unsupported_action_type",
                }
            )
            continue

        if bool(action.get("blocking")):
            blocking_priority = priority

    return {
        "ok": True,
        "executed": executed,
        "blocked": blocked,
        "pendingConfirms": pending_confirms,
        "uiCommands": ui_commands,
        "executedCount": len(executed),
        "blockedCount": len(blocked),
        "pendingConfirmCount": len(pending_confirms),
    }


def _is_blocked_by_previous(blocking_priority: int | None, current_priority: int, action_type: str) -> bool:
    if blocking_priority is None:
        return False
    if current_priority > blocking_priority:
        return True
    if current_priority == blocking_priority and action_type not in {"confirm", "stop"}:
        return True
    return False


def _resolve_action_id(action: dict[str, Any], ordinal: int) -> str:
    action_id = str(action.get("actionId", "")).strip()
    if action_id:
        return action_id
    payload = action.get("payload")
    if isinstance(payload, dict):
        payload_id = str(payload.get("actionId", "")).strip()
        if payload_id:
            return payload_id
    return f"a{int(max(1, ordinal))}"


def _as_int(value: Any, default: int) -> int:
    try:
        if value is None or isinstance(value, bool):
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)
