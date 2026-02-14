from __future__ import annotations

import os
from typing import Any

import httpx

from .base import PlannerBackend


class HttpPlannerBackend(PlannerBackend):
    backend = "http"

    def __init__(self) -> None:
        endpoint = str(os.getenv("BYES_PLANNER_ENDPOINT", "")).strip() or "http://127.0.0.1:19211/plan"
        self.endpoint = endpoint
        self.model = os.getenv("BYES_PLANNER_MODEL_ID", "http-planner")

    def generate_plan(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        outbound_payload = dict(request_payload)
        allow_path = str(os.getenv("BYES_PLANNER_ALLOW_RUN_PACKAGE_PATH", "0")).strip().lower() in {"1", "true", "yes", "on"}
        if not allow_path:
            outbound_payload.pop("runPackagePath", None)
        used_request_fallback = False
        response_payload: dict[str, Any]
        with httpx.Client(timeout=20.0) as client:
            try:
                response = client.post(self.endpoint, json=outbound_payload, headers={"X-Endpoint": self.endpoint})
                response.raise_for_status()
                response_payload = response.json()
            except Exception:
                legacy_payload = _to_legacy_planner_request(outbound_payload)
                if not legacy_payload:
                    raise
                used_request_fallback = True
                response = client.post(self.endpoint, json=legacy_payload, headers={"X-Endpoint": self.endpoint})
                response.raise_for_status()
                response_payload = response.json()
        if not isinstance(response_payload, dict):
            raise RuntimeError("planner http response must be object")
        meta = response_payload.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        planner = meta.get("planner")
        planner = planner if isinstance(planner, dict) else {}
        planner.setdefault("backend", "http")
        planner.setdefault("model", self.model)
        planner.setdefault("endpoint", self.endpoint)
        if used_request_fallback:
            planner["requestFallbackUsed"] = True
            if not isinstance(planner.get("fallbackUsed"), bool):
                planner["fallbackUsed"] = True
            if not str(planner.get("fallbackReason", "")).strip():
                planner["fallbackReason"] = "request_schema_fallback"
        meta["planner"] = planner
        response_payload["meta"] = meta
        return response_payload


def _to_legacy_planner_request(payload: dict[str, Any]) -> dict[str, Any] | None:
    if str(payload.get("schemaVersion", "")).strip() != "byes.plan_request.v1":
        return None
    context_pack = payload.get("contextPack")
    context_pack = context_pack if isinstance(context_pack, dict) else {"schemaVersion": "pov.context.v1"}
    risk_summary = payload.get("riskSummary")
    risk_summary = risk_summary if isinstance(risk_summary, dict) else {}
    constraints = payload.get("constraints")
    constraints = constraints if isinstance(constraints, dict) else {}
    context_budget = payload.get("contextBudget")
    context_budget = context_budget if isinstance(context_budget, dict) else {}
    legacy = {
        "schemaVersion": "byes.planner_request.v1",
        "runId": payload.get("runId"),
        "frameSeq": payload.get("frameSeq"),
        "contextPack": context_pack,
        "contextBudget": context_budget,
        "riskSummary": risk_summary,
        "constraints": constraints,
    }
    for key in ("provider", "povIr", "segContext", "runPackagePath"):
        if key in payload:
            legacy[key] = payload.get(key)
    return legacy
