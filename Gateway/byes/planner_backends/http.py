from __future__ import annotations

import os
from typing import Any

import httpx

from .base import PlannerBackend


class HttpPlannerBackend(PlannerBackend):
    backend = "http"

    def __init__(self) -> None:
        endpoint = str(os.getenv("BYES_PLANNER_ENDPOINT", "")).strip()
        if not endpoint:
            raise RuntimeError("BYES_PLANNER_ENDPOINT is required for http planner backend")
        self.endpoint = endpoint
        self.model = os.getenv("BYES_PLANNER_MODEL_ID", "http-planner")

    def generate_plan(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(self.endpoint, json=request_payload)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("planner http response must be object")
        return payload
