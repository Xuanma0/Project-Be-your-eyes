from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from byes.pov_context import build_context_pack, finalize_context_pack_text, render_context_text
from byes.planner_backends.base import PlannerBackend
from byes.planner_registry import get_planner_backend
from byes.safety_kernel import apply_guardrails, classify_risk_level


def _now_ms() -> int:
    return int(time.time() * 1000)


def load_events_v1_rows(run_package_dir: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], Path | None]:
    events_rel = str(manifest.get("eventsV1Jsonl", "")).strip() or "events/events_v1.jsonl"
    events_path = run_package_dir / events_rel
    if not events_path.exists():
        return [], None
    rows: list[dict[str, Any]] = []
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows, events_path


def extract_risk_summary(events_rows: list[dict[str, Any]], frame_seq: int | None = None) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in events_rows:
        name = str(row.get("name", "")).strip().lower()
        phase = str(row.get("phase", "")).strip().lower()
        status = str(row.get("status", "")).strip().lower()
        if name != "risk.hazards" or phase != "result" or status != "ok":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        seq = _as_int(row.get("frameSeq"))
        if frame_seq is not None and seq != frame_seq:
            continue
        candidates.append(row)

    if not candidates and frame_seq is not None:
        candidates = [
            row
            for row in events_rows
            if str(row.get("name", "")).strip().lower() == "risk.hazards"
            and str(row.get("phase", "")).strip().lower() == "result"
            and str(row.get("status", "")).strip().lower() == "ok"
            and isinstance(row.get("payload"), dict)
        ]

    if not candidates:
        return {
            "hazardsTop": [],
            "riskLevel": "low",
            "riskLatencyP90": None,
            "missCriticalCount": None,
            "critical_fn": None,
        }

    chosen = sorted(
        candidates,
        key=lambda item: (_as_int(item.get("tsMs")) or 0, _as_int(item.get("frameSeq")) or 0),
    )[-1]
    payload = chosen.get("payload", {})
    payload = payload if isinstance(payload, dict) else {}
    hazards_raw = payload.get("hazards")
    hazards_raw = hazards_raw if isinstance(hazards_raw, list) else []
    hazards_top: list[dict[str, Any]] = []
    for hazard in hazards_raw[:5]:
        if not isinstance(hazard, dict):
            continue
        item = {
            "hazardKind": str(hazard.get("hazardKind", "")).strip(),
            "severity": str(hazard.get("severity", "")).strip().lower() or "warning",
        }
        score = hazard.get("score")
        if isinstance(score, (int, float)):
            item["score"] = float(score)
        hazards_top.append(item)
    risk_level = classify_risk_level(hazards_top)
    latency = _as_int(chosen.get("latencyMs"))
    return {
        "hazardsTop": hazards_top,
        "riskLevel": risk_level,
        "riskLatencyP90": latency,
        "missCriticalCount": None,
        "critical_fn": None,
    }


def build_planner_request(
    *,
    run_id: str,
    frame_seq: int | None,
    context_pack: dict[str, Any],
    risk_summary: dict[str, Any],
    constraints: dict[str, Any],
    run_package_path: str | None = None,
) -> dict[str, Any]:
    normalized_constraints = {
        "allowConfirm": bool(constraints.get("allowConfirm", True)),
        "allowHaptic": bool(constraints.get("allowHaptic", False)),
        "maxActions": max(1, int(constraints.get("maxActions", 3) or 3)),
    }
    budget = context_pack.get("budget", {})
    budget = budget if isinstance(budget, dict) else {}
    payload = {
        "schemaVersion": "byes.planner_request.v1",
        "runId": run_id,
        "frameSeq": frame_seq if isinstance(frame_seq, int) else None,
        "contextPack": context_pack,
        "contextBudget": {
            "maxChars": int(budget.get("maxChars", 0) or 0),
            "maxTokensApprox": int(budget.get("maxTokensApprox", 0) or 0),
            "mode": str(budget.get("mode", "decisions_plus_highlights")),
        },
        "riskSummary": risk_summary,
        "constraints": normalized_constraints,
    }
    allow_path = str(os.getenv("BYES_PLANNER_ALLOW_RUN_PACKAGE_PATH", "0")).strip().lower() in {"1", "true", "yes", "on"}
    run_package_path_text = str(run_package_path or "").strip()
    if allow_path and run_package_path_text:
        payload["runPackagePath"] = run_package_path_text
    return payload


def generate_action_plan(
    *,
    pov_ir: dict[str, Any],
    run_id: str,
    frame_seq: int | None,
    budget: dict[str, Any],
    mode: str,
    constraints: dict[str, Any],
    events_rows: list[dict[str, Any]],
    run_package_path: str | None = None,
    backend: PlannerBackend | None = None,
) -> dict[str, Any]:
    context_pack = build_context_pack(pov_ir, budget=budget, mode=mode)
    context_text = render_context_text(context_pack)
    context_pack = finalize_context_pack_text(context_pack, context_text, _now_ms())

    risk_summary = extract_risk_summary(events_rows, frame_seq=frame_seq)
    risk_level = str(risk_summary.get("riskLevel", "low")).strip().lower() or "low"

    planner_backend = backend if backend is not None else get_planner_backend()
    planner_request = build_planner_request(
        run_id=run_id,
        frame_seq=frame_seq,
        context_pack=context_pack,
        risk_summary=risk_summary,
        constraints=constraints,
        run_package_path=run_package_path,
    )
    draft_plan = planner_backend.generate_plan(planner_request)
    if not isinstance(draft_plan, dict):
        raise RuntimeError("planner backend returned invalid plan")

    if str(draft_plan.get("schemaVersion", "")).strip() != "byes.action_plan.v1":
        draft_plan["schemaVersion"] = "byes.action_plan.v1"
    draft_plan["runId"] = run_id
    draft_plan["frameSeq"] = frame_seq if isinstance(frame_seq, int) else None
    if _as_int(draft_plan.get("generatedAtMs")) is None:
        draft_plan["generatedAtMs"] = _now_ms()
    backend_risk_level = str(draft_plan.get("riskLevel", "")).strip().lower()
    if risk_level == "low" and backend_risk_level in {"medium", "high", "critical"}:
        draft_plan["riskLevel"] = backend_risk_level
        risk_level = backend_risk_level
    else:
        draft_plan["riskLevel"] = risk_level

    guarded_plan, guardrails_applied, findings = apply_guardrails(
        draft_plan,
        risk_level=risk_level,
        constraints=constraints,
    )
    meta = guarded_plan.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    planner_meta = meta.get("planner")
    planner_meta = planner_meta if isinstance(planner_meta, dict) else {}
    planner_meta.setdefault("backend", getattr(planner_backend, "backend", "mock"))
    planner_meta.setdefault("model", getattr(planner_backend, "model", None))
    planner_meta.setdefault("endpoint", getattr(planner_backend, "endpoint", None))
    meta["planner"] = planner_meta
    budget_meta = meta.get("budget")
    budget_meta = budget_meta if isinstance(budget_meta, dict) else {}
    budget_meta["contextMaxTokensApprox"] = int(context_pack.get("budget", {}).get("maxTokensApprox", 0) or 0)
    budget_meta["contextMaxChars"] = int(context_pack.get("budget", {}).get("maxChars", 0) or 0)
    budget_meta["mode"] = str(context_pack.get("budget", {}).get("mode", "decisions_plus_highlights"))
    meta["budget"] = budget_meta
    safety_meta = meta.get("safety")
    safety_meta = safety_meta if isinstance(safety_meta, dict) else {}
    safety_meta["guardrailsApplied"] = list(guardrails_applied)
    if findings:
        safety_meta["notes"] = f"findings={len(findings)}"
    meta["safety"] = safety_meta
    guarded_plan["meta"] = meta

    return {
        "plan": guarded_plan,
        "contextPack": context_pack,
        "riskSummary": risk_summary,
        "guardrailsApplied": list(guardrails_applied),
        "findings": findings,
        "planner": planner_meta,
    }


def summarize_plan_for_report(bundle: dict[str, Any]) -> dict[str, Any]:
    plan = bundle.get("plan", {})
    plan = plan if isinstance(plan, dict) else {}
    actions = plan.get("actions", [])
    actions = [item for item in actions if isinstance(item, dict)]
    guardrails = bundle.get("guardrailsApplied", [])
    guardrails = guardrails if isinstance(guardrails, list) else []
    types = [str(item.get("type", "")).strip() for item in actions if str(item.get("type", "")).strip()]
    stop_count = sum(1 for item in actions if str(item.get("type", "")).strip().lower() == "stop")
    confirm_action_count = sum(1 for item in actions if str(item.get("type", "")).strip().lower() == "confirm")
    blocking_count = sum(1 for item in actions if bool(item.get("blocking")))
    requires_confirm_count = sum(1 for item in actions if bool(item.get("requiresConfirm")))
    planner_meta = bundle.get("planner", {})
    planner_meta = planner_meta if isinstance(planner_meta, dict) else {}
    action_details: list[dict[str, Any]] = []
    for item in actions:
        payload = item.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        action_details.append(
            {
                "type": str(item.get("type", "")).strip().lower(),
                "priority": _as_int(item.get("priority")),
                "requiresConfirm": bool(item.get("requiresConfirm")),
                "blocking": bool(item.get("blocking")),
                "payload": payload,
            }
        )

    return {
        "present": True,
        "planner": {
            "backend": planner_meta.get("backend"),
            "model": planner_meta.get("model"),
            "endpoint": planner_meta.get("endpoint"),
            "provider": planner_meta.get("plannerProvider") or planner_meta.get("provider"),
            "promptVersion": planner_meta.get("promptVersion"),
            "fallbackUsed": planner_meta.get("fallbackUsed"),
            "fallbackReason": planner_meta.get("fallbackReason"),
            "jsonValid": planner_meta.get("jsonValid"),
        },
        "riskLevel": str(plan.get("riskLevel", "")).strip() or "low",
        "actions": {
            "count": len(actions),
            "types": types,
            "stopCount": stop_count,
            "confirmActionCount": confirm_action_count,
            "blockingCount": blocking_count,
            "requiresConfirmCount": requires_confirm_count,
        },
        "guardrailsApplied": guardrails,
        "findingsCount": len(bundle.get("findings", [])) if isinstance(bundle.get("findings"), list) else 0,
        "actionDetails": action_details,
    }


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None
