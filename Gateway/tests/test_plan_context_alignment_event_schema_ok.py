from __future__ import annotations

import json
from pathlib import Path


def test_plan_context_alignment_event_schema_ok() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "run_package_with_plan_context_alignment_min"
    events_path = fixture / "events" / "events_v1.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    event = next((row for row in rows if str(row.get("name", "")).strip().lower() == "plan.context_alignment"), None)
    assert isinstance(event, dict)

    payload = event.get("payload")
    assert isinstance(payload, dict)
    assert str(payload.get("schemaVersion", "")).strip() == "plan.context_alignment.v1"

    seg = payload.get("seg")
    seg = seg if isinstance(seg, dict) else {}
    pov = payload.get("pov")
    pov = pov if isinstance(pov, dict) else {}

    assert isinstance(seg.get("present"), bool)
    assert isinstance(seg.get("labelCount"), int)
    assert isinstance(seg.get("hit"), bool)
    assert isinstance(seg.get("coverage"), (int, float))
    assert isinstance(seg.get("matched"), list)

    assert isinstance(pov.get("present"), bool)
    assert isinstance(pov.get("tokenCount"), int)
    assert isinstance(pov.get("hit"), bool)
    assert isinstance(pov.get("coverage"), (int, float))
    assert isinstance(pov.get("hitCount"), int)

    assert isinstance(payload.get("contextUsed"), bool)
