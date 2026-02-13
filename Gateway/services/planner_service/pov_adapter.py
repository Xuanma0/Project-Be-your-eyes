from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_pov_ir(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"pov_ir_not_found:{path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return parse_pov_ir_obj(payload)


def parse_pov_ir_obj(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("pov_ir_not_object")
    if str(payload.get("schemaVersion", "")).strip() != "pov.ir.v1":
        raise ValueError("pov_ir_schema_version_invalid")
    run_id = str(payload.get("runId", "")).strip()
    if not run_id:
        raise ValueError("pov_ir_run_id_missing")
    decisions = payload.get("decisionPoints")
    if not isinstance(decisions, list):
        raise ValueError("pov_ir_decision_points_missing")
    for key in ("events", "highlights", "tokens"):
        rows = payload.get(key)
        if rows is None:
            payload[key] = []
            continue
        if not isinstance(rows, list):
            raise ValueError(f"pov_ir_{key}_invalid")
    return payload


def pov_to_action_plan(
    pov: dict[str, Any],
    constraints: dict[str, Any] | None,
    *,
    run_id: str,
    frame_seq: int | None,
    generated_at_ms: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    constraints_payload = constraints if isinstance(constraints, dict) else {}
    allow_confirm = bool(constraints_payload.get("allowConfirm", True))
    max_actions = max(1, int(constraints_payload.get("maxActions", 3) or 3))

    decisions = pov.get("decisionPoints")
    decisions = [row for row in decisions if isinstance(row, dict)] if isinstance(decisions, list) else []
    decisions = sorted(decisions, key=lambda row: int(row.get("t0Ms", 0) or 0))
    decision_ids = {str(row.get("id", "")).strip() for row in decisions if str(row.get("id", "")).strip()}

    events = pov.get("events")
    events = [row for row in events if isinstance(row, dict)] if isinstance(events, list) else []
    highlights = pov.get("highlights")
    highlights = [row for row in highlights if isinstance(row, dict)] if isinstance(highlights, list) else []

    risk_level = _infer_risk_level(decisions, events)

    actions: list[dict[str, Any]] = []
    priority = 0
    emitted_stop = False

    for row in decisions:
        decision_id = str(row.get("id", "")).strip()
        source_ids = [decision_id] if decision_id else []
        decision_text = _decision_text(row)
        need_stop = _decision_requires_stop(row)
        need_confirm = _decision_requires_confirm(row)

        if need_stop and not emitted_stop:
            actions.append(
                {
                    "type": "stop",
                    "priority": priority,
                    "payload": {
                        "reason": "pov_decision_stop",
                        "text": decision_text or "POV decision requires stop.",
                        "source": "pov",
                        "sourceDecisionIds": source_ids,
                    },
                    "requiresConfirm": False,
                    "blocking": True,
                }
            )
            emitted_stop = True
            priority += 1

        if need_confirm and allow_confirm:
            confirm_id = f"confirm-{run_id}-{decision_id or priority}"
            actions.append(
                {
                    "type": "confirm",
                    "priority": priority,
                    "payload": {
                        "text": decision_text or "Confirm planned action.",
                        "confirmId": confirm_id,
                        "timeoutMs": 3000,
                        "source": "pov",
                        "sourceDecisionIds": source_ids,
                    },
                    "requiresConfirm": False,
                    "blocking": True,
                }
            )
            priority += 1

    highlight_texts = [str(row.get("text", "")).strip() for row in highlights if str(row.get("text", "")).strip()]
    if highlight_texts:
        highlight_decision_ids = _resolve_highlight_decision_ids(highlights, decisions)
        merged_highlights = " ".join(highlight_texts[:2]).strip()
        actions.append(
            {
                "type": "speak",
                "priority": priority,
                "payload": {
                    "text": merged_highlights,
                    "source": "pov",
                    "sourceDecisionIds": highlight_decision_ids,
                },
                "requiresConfirm": risk_level in {"high", "critical"},
                "blocking": False,
            }
        )
        priority += 1

    if not actions and decisions:
        first = decisions[0]
        decision_id = str(first.get("id", "")).strip()
        actions.append(
            {
                "type": "speak",
                "priority": 0,
                "payload": {
                    "text": _decision_text(first) or "POV decision available.",
                    "source": "pov",
                    "sourceDecisionIds": [decision_id] if decision_id else [],
                },
                "requiresConfirm": False,
                "blocking": False,
            }
        )
    if not actions:
        actions.append(
            {
                "type": "speak",
                "priority": 0,
                "payload": {"text": "POV adapter produced no explicit action.", "source": "pov", "sourceDecisionIds": []},
                "requiresConfirm": False,
                "blocking": False,
            }
        )

    actions = sorted(actions, key=lambda row: _priority_value(row))[:max_actions]

    plan = {
        "schemaVersion": "byes.action_plan.v1",
        "runId": run_id,
        "frameSeq": frame_seq if isinstance(frame_seq, int) else None,
        "generatedAtMs": int(generated_at_ms),
        "intent": "pov_compiler_adapter",
        "riskLevel": risk_level,
        "ttlMs": 2000,
        "actions": actions,
        "meta": {
            "planner": {
                "backend": "pov",
                "model": "pov-ir-v1",
                "endpoint": None,
                "plannerProvider": "pov",
                "promptVersion": "n/a",
                "fallbackUsed": False,
                "fallbackReason": None,
                "jsonValid": True,
            },
            "budget": {
                "contextMaxTokensApprox": 0,
                "contextMaxChars": 0,
                "mode": "decisions_plus_highlights",
            },
            "safety": {"guardrailsApplied": []},
        },
    }

    diagnostics = {
        "decisionCount": len(decisions),
        "mappedDecisionCount": _mapped_decision_count(actions, decision_ids),
        "riskLevel": risk_level,
    }
    return plan, diagnostics


def _decision_requires_stop(row: dict[str, Any]) -> bool:
    blob = " ".join(
        [
            str(row.get("state", "")),
            str(row.get("action", "")),
            str(row.get("outcome", "")),
            str(row.get("severity", "")),
            str(row.get("label", "")),
            str(row.get("intent", "")),
        ]
    ).lower()
    return any(token in blob for token in ("stop", "critical", "danger", "hazard"))


def _decision_requires_confirm(row: dict[str, Any]) -> bool:
    blob = " ".join(
        [
            str(row.get("state", "")),
            str(row.get("action", "")),
            str(row.get("outcome", "")),
            str(row.get("constraints", "")),
        ]
    ).lower()
    return any(token in blob for token in ("confirm", "wait", "clarify", "ask"))


def _infer_risk_level(decisions: list[dict[str, Any]], events: list[dict[str, Any]]) -> str:
    for row in decisions:
        if _decision_requires_stop(row):
            return "critical"
    for row in events:
        severity = str(row.get("severity", "")).strip().lower()
        if severity == "critical":
            return "critical"
        if severity in {"high", "warning", "medium"}:
            return "medium"
    return "low"


def _decision_text(row: dict[str, Any]) -> str:
    state = str(row.get("state", "")).strip()
    action = str(row.get("action", "")).strip()
    outcome = str(row.get("outcome", "")).strip()
    parts = [part for part in [state, action, outcome] if part]
    return " -> ".join(parts).strip()


def _mapped_decision_count(actions: list[dict[str, Any]], valid_ids: set[str]) -> int:
    mapped: set[str] = set()
    for row in actions:
        payload = row.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        ids = payload.get("sourceDecisionIds")
        ids = ids if isinstance(ids, list) else []
        for item in ids:
            text = str(item).strip()
            if text and text in valid_ids:
                mapped.add(text)
    return len(mapped)


def _resolve_highlight_decision_ids(highlights: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> list[str]:
    ordered_decisions = sorted(
        [row for row in decisions if isinstance(row, dict)],
        key=lambda row: int(row.get("t0Ms", 0) or 0),
    )
    out: list[str] = []
    for highlight in highlights:
        if not isinstance(highlight, dict):
            continue
        t_ms = _as_int(highlight.get("tMs"))
        if t_ms is None:
            continue
        decision_id = _match_decision_id_for_time(ordered_decisions, t_ms)
        if decision_id and decision_id not in out:
            out.append(decision_id)
    return out


def _match_decision_id_for_time(decisions: list[dict[str, Any]], t_ms: int) -> str | None:
    best_prior: tuple[int, str] | None = None
    for row in decisions:
        decision_id = str(row.get("id", "")).strip()
        if not decision_id:
            continue
        t0 = _as_int(row.get("t0Ms"))
        t1 = _as_int(row.get("t1Ms"))
        if t0 is None and t1 is None:
            continue
        if t0 is not None and t1 is not None and t0 <= t_ms <= t1:
            return decision_id
        if t0 is not None and t0 <= t_ms:
            if best_prior is None or t0 > best_prior[0]:
                best_prior = (t0, decision_id)
    if best_prior is not None:
        return best_prior[1]
    if decisions:
        fallback_id = str(decisions[0].get("id", "")).strip()
        if fallback_id:
            return fallback_id
    return None


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
