from __future__ import annotations

import json
from pathlib import Path

import jsonschema


def test_plan_context_pack_fixture_schema_ok() -> None:
    tests_dir = Path(__file__).resolve().parent
    fixture = tests_dir / "fixtures" / "run_package_with_plan_context_pack_min" / "events" / "events_v1.jsonl"
    schema_path = tests_dir.parent / "contracts" / "plan.context_pack.v1.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    lines = [line for line in fixture.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    rows = [json.loads(line) for line in lines]
    payload = next(
        row.get("payload")
        for row in rows
        if str(row.get("name", "")).strip().lower() == "plan.context_pack"
    )
    assert isinstance(payload, dict)
    jsonschema.validate(payload, schema)
    assert payload.get("schemaVersion") == "plan.context_pack.v1"
