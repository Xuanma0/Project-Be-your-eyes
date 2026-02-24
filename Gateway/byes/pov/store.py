from __future__ import annotations

import copy
import time
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


def _count_rows(payload: dict[str, Any], key: str) -> int:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return 0
    return sum(1 for row in rows if isinstance(row, dict))


class PovStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def set(self, run_id: str, pov_ir: dict[str, Any]) -> None:
        run_id_text = str(run_id or "").strip()
        if not run_id_text:
            raise ValueError("run_id is required")
        if not isinstance(pov_ir, dict):
            raise ValueError("pov_ir must be object")
        self._rows[run_id_text] = {
            "pov": copy.deepcopy(pov_ir),
            "tsMs": _now_ms(),
        }

    def get(self, run_id: str) -> dict[str, Any] | None:
        run_id_text = str(run_id or "").strip()
        if not run_id_text:
            return None
        row = self._rows.get(run_id_text)
        if not isinstance(row, dict):
            return None
        pov = row.get("pov")
        if not isinstance(pov, dict):
            return None
        return copy.deepcopy(pov)

    def summary(self, run_id: str) -> dict[str, Any]:
        run_id_text = str(run_id or "").strip()
        row = self._rows.get(run_id_text) if run_id_text else None
        if not isinstance(row, dict):
            return {
                "present": False,
                "runId": run_id_text or None,
                "counts": {"decisions": 0, "events": 0, "highlights": 0, "tokens": 0},
                "createdAtMs": None,
            }
        pov = row.get("pov")
        pov = pov if isinstance(pov, dict) else {}
        return {
            "present": True,
            "runId": run_id_text or str(pov.get("runId", "")).strip() or None,
            "counts": {
                "decisions": _count_rows(pov, "decisionPoints"),
                "events": _count_rows(pov, "events"),
                "highlights": _count_rows(pov, "highlights"),
                "tokens": _count_rows(pov, "tokens"),
            },
            "createdAtMs": int(row.get("tsMs", 0) or 0),
        }
