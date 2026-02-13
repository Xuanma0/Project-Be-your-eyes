from __future__ import annotations

from typing import Any


class PlannerBackend:
    backend: str = "base"
    model: str | None = None
    endpoint: str | None = None

    def generate_plan(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
