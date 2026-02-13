from __future__ import annotations

import os
import time
from typing import Any

from flask import Flask, jsonify, request

app = Flask(__name__)


_ALLOWED_RISK = {"low", "medium", "high", "critical"}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_hazards(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    out: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "hazardKind": str(item.get("hazardKind", "")).strip(),
                "severity": str(item.get("severity", "warning")).strip().lower() or "warning",
                "score": item.get("score"),
            }
        )
    return out


def _infer_risk_level(hazards: list[dict[str, Any]]) -> str:
    if any(str(item.get("severity", "")).strip().lower() == "critical" for item in hazards):
        return "critical"
    if any(str(item.get("severity", "")).strip().lower() in {"high", "severe"} for item in hazards):
        return "high"
    if any(str(item.get("severity", "")).strip().lower() in {"warning", "warn", "medium"} for item in hazards):
        return "medium"
    return "low"


def _trim_actions(actions: list[dict[str, Any]], max_actions: int) -> list[dict[str, Any]]:
    ordered = sorted(actions, key=lambda row: int(row.get("priority", 9999) or 9999))
    return ordered[: max(1, int(max_actions))]


@app.get("/healthz")
def healthz() -> Any:
    return jsonify({"ok": True, "service": "reference-planner-v1"})


@app.post("/plan")
def plan() -> Any:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "request body must be object"}), 400
    if str(payload.get("schemaVersion", "")).strip() != "byes.planner_request.v1":
        return jsonify({"ok": False, "error": "schemaVersion must be byes.planner_request.v1"}), 400

    run_id = str(payload.get("runId", "")).strip() or "planner-run"
    frame_seq = payload.get("frameSeq")
    frame_seq = int(frame_seq) if isinstance(frame_seq, int) else None

    risk_summary = payload.get("riskSummary")
    risk_summary = risk_summary if isinstance(risk_summary, dict) else {}
    hazards = _normalize_hazards(risk_summary.get("hazardsTop"))
    risk_level = _infer_risk_level(hazards)
    if risk_level not in _ALLOWED_RISK:
        risk_level = "low"

    constraints = payload.get("constraints")
    constraints = constraints if isinstance(constraints, dict) else {}
    max_actions = int(constraints.get("maxActions", 3) or 3)

    actions: list[dict[str, Any]] = []
    if risk_level == "critical":
        actions.append(
            {
                "type": "confirm",
                "priority": 0,
                "payload": {"text": "High risk ahead. Stop?", "confirmId": f"confirm-{run_id}-{frame_seq or 1}", "timeoutMs": 3000},
                "requiresConfirm": False,
                "blocking": True,
            }
        )
        actions.append(
            {
                "type": "speak",
                "priority": 1,
                "payload": {"text": "High risk zone detected."},
                "requiresConfirm": False,
                "blocking": False,
            }
        )
    elif risk_level in {"medium", "high"}:
        actions.append(
            {
                "type": "speak",
                "priority": 0,
                "payload": {"text": "Caution. Potential hazards ahead."},
                "requiresConfirm": False,
                "blocking": False,
            }
        )
        actions.append(
            {
                "type": "overlay",
                "priority": 1,
                "payload": {"label": "CAUTION", "text": "Potential hazard region"},
                "requiresConfirm": False,
                "blocking": False,
            }
        )
    else:
        actions.append(
            {
                "type": "speak",
                "priority": 0,
                "payload": {"text": "Path looks clear."},
                "requiresConfirm": False,
                "blocking": False,
            }
        )

    actions = _trim_actions(actions, max_actions=max_actions)
    endpoint = request.headers.get("X-Endpoint") or os.getenv("PLANNER_SERVICE_ENDPOINT", "http://127.0.0.1:19211/plan")

    response_payload = {
        "schemaVersion": "byes.action_plan.v1",
        "runId": run_id,
        "frameSeq": frame_seq,
        "generatedAtMs": _now_ms(),
        "intent": "assist_navigation",
        "riskLevel": risk_level,
        "ttlMs": 2000,
        "actions": actions,
        "meta": {
            "planner": {
                "backend": "http",
                "model": "reference-planner-v1",
                "endpoint": endpoint,
            },
            "budget": {
                "contextMaxTokensApprox": int(payload.get("contextBudget", {}).get("maxTokensApprox", 0) or 0)
                if isinstance(payload.get("contextBudget"), dict)
                else 0,
                "contextMaxChars": int(payload.get("contextBudget", {}).get("maxChars", 0) or 0)
                if isinstance(payload.get("contextBudget"), dict)
                else 0,
                "mode": str(payload.get("contextBudget", {}).get("mode", "decisions_plus_highlights"))
                if isinstance(payload.get("contextBudget"), dict)
                else "decisions_plus_highlights",
            },
            "safety": {"guardrailsApplied": []},
        },
    }
    return jsonify(response_payload)


if __name__ == "__main__":
    host = os.getenv("PLANNER_SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("PLANNER_SERVICE_PORT", "19211"))
    app.run(host=host, port=port)
