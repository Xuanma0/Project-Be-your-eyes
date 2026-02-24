from __future__ import annotations

import os

from byes.planner_backends.base import PlannerBackend
from byes.planner_backends.http import HttpPlannerBackend
from byes.planner_backends.mock import MockPlannerBackend


def get_planner_backend() -> PlannerBackend:
    backend = str(os.getenv("BYES_PLANNER_BACKEND", "mock")).strip().lower()
    if backend == "http":
        return HttpPlannerBackend()
    return MockPlannerBackend()
