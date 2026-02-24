from __future__ import annotations

import json
from pathlib import Path

import jsonschema


def test_frame_e2e_fixture_schema_ok() -> None:
    tests_dir = Path(__file__).resolve().parent
    fixture = tests_dir / "fixtures" / "run_package_with_frame_e2e_min" / "events" / "events_v1.jsonl"
    schema_path = tests_dir.parent / "contracts" / "frame.e2e.v1.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    lines = [line for line in fixture.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    rows = [json.loads(line) for line in lines]
    payloads = [
        row.get("payload")
        for row in rows
        if str(row.get("name", "")).strip().lower() == "frame.e2e"
    ]
    assert payloads
    for payload in payloads:
        assert isinstance(payload, dict)
        jsonschema.validate(payload, schema)
        assert payload.get("schemaVersion") == "frame.e2e.v1"
