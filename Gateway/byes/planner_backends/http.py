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
        with httpx.Client(timeout=20.0) as client:
            response = client.post(self.endpoint, json=outbound_payload, headers={"X-Endpoint": self.endpoint})
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("planner http response must be object")
        meta = payload.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        planner = meta.get("planner")
        planner = planner if isinstance(planner, dict) else {}
        planner.setdefault("backend", "http")
        planner.setdefault("model", self.model)
        planner.setdefault("endpoint", self.endpoint)
        meta["planner"] = planner
        payload["meta"] = meta
        return payload
