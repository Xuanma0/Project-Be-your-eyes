from __future__ import annotations

import json
from pathlib import Path

from main import _try_append_frame_e2e_event


def test_frame_e2e_emits_once_per_frame(tmp_path: Path) -> None:
    events_path = tmp_path / "events_v1.jsonl"
    seed = {
        "schemaVersion": "byes.event.v1",
        "tsMs": 1000,
        "runId": "run-one",
        "frameSeq": 1,
        "component": "gateway",
        "category": "plan",
        "name": "plan.generate",
        "phase": "result",
        "status": "ok",
        "latencyMs": 12,
        "payload": {"riskLevel": "low", "actionsCount": 1},
    }
    events_path.write_text(json.dumps(seed, ensure_ascii=False) + "\n", encoding="utf-8")

    assert _try_append_frame_e2e_event(
        events_path=events_path,
        run_id="run-one",
        frame_seq=1,
        t1_ms=1100,
        t0_hint_ms=1000,
        plan_ms=12,
        plan_present=True,
    )
    assert _try_append_frame_e2e_event(
        events_path=events_path,
        run_id="run-one",
        frame_seq=1,
        t1_ms=1200,
        t0_hint_ms=1000,
        execute_ms=18,
        execute_present=True,
    )

    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    frame_rows = [row for row in rows if str(row.get("name", "")).strip().lower() == "frame.e2e"]
    assert len(frame_rows) == 1
