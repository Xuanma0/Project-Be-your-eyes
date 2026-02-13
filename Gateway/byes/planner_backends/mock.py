from __future__ import annotations

import os
import time
from typing import Any

from .base import PlannerBackend


def _now_ms() -> int:
    return int(time.time() * 1000)


class MockPlannerBackend(PlannerBackend):
    backend = "mock"

    def __init__(self) -> None:
        self.model = os.getenv("BYES_PLANNER_MODEL_ID", "mock-planner-v1")
        self.endpoint = None

    def generate_plan(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        run_id = str(request_payload.get("runId", "")).strip() or "planner-run"
        frame_seq = request_payload.get("frameSeq")
        risk_summary = request_payload.get("riskSummary", {})
        risk_summary = risk_summary if isinstance(risk_summary, dict) else {}
        risk_level = str(risk_summary.get("riskLevel", "low")).strip().lower() or "low"
        constraints = request_payload.get("constraints", {})
        constraints = constraints if isinstance(constraints, dict) else {}
        allow_confirm = bool(constraints.get("allowConfirm", True))

        actions: list[dict[str, Any]] = []
        if risk_level == "critical":
            if allow_confirm:
                actions.append(
                    {
                        "type": "confirm",
                        "priority": 0,
                        "payload": {"text": "High risk detected ahead. Confirm stop?"},
                        "requiresConfirm": False,
                        "blocking": True,
                    }
                )
            actions.append(
                {
                    "type": "speak",
                    "priority": 1,
                    "payload": {"text": "High risk zone detected. Please proceed carefully."},
                    "requiresConfirm": False,
                    "blocking": False,
                }
            )
        else:
            actions.append(
                {
                    "type": "speak",
                    "priority": 0,
                    "payload": {"text": "Environment appears stable. You may continue."},
                    "requiresConfirm": False,
                    "blocking": False,
                }
            )

        context_budget = request_payload.get("contextBudget", {})
        context_budget = context_budget if isinstance(context_budget, dict) else {}
        return {
            "schemaVersion": "byes.action_plan.v1",
            "runId": run_id,
            "frameSeq": frame_seq if isinstance(frame_seq, int) else None,
            "generatedAtMs": _now_ms(),
            "intent": "assist_navigation",
            "riskLevel": risk_level if risk_level in {"low", "medium", "high", "critical"} else "low",
            "ttlMs": 2000,
            "actions": actions,
            "meta": {
                "planner": {
                    "backend": self.backend,
                    "model": self.model,
                    "endpoint": self.endpoint,
                },
                "budget": {
                    "contextMaxTokensApprox": int(context_budget.get("maxTokensApprox", 0) or 0),
                    "contextMaxChars": int(context_budget.get("maxChars", 0) or 0),
                    "mode": str(context_budget.get("mode", "decisions_plus_highlights")),
                },
                "safety": {"guardrailsApplied": []},
            },
        }
