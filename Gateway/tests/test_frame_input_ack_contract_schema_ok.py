from __future__ import annotations

import json
from pathlib import Path

import jsonschema


def test_frame_input_ack_and_user_e2e_fixture_schema_ok() -> None:
    tests_dir = Path(__file__).resolve().parent
    fixture = tests_dir / "fixtures" / "run_package_with_frame_user_e2e_min" / "events" / "events_v1.jsonl"
    frame_input_schema_path = tests_dir.parent / "contracts" / "frame.input.v1.json"
    frame_ack_schema_path = tests_dir.parent / "contracts" / "frame.ack.v1.json"
    frame_e2e_schema_path = tests_dir.parent / "contracts" / "frame.e2e.v1.json"

    frame_input_schema = json.loads(frame_input_schema_path.read_text(encoding="utf-8-sig"))
    frame_ack_schema = json.loads(frame_ack_schema_path.read_text(encoding="utf-8-sig"))
    frame_e2e_schema = json.loads(frame_e2e_schema_path.read_text(encoding="utf-8-sig"))
    rows = [json.loads(line) for line in fixture.read_text(encoding="utf-8-sig").splitlines() if line.strip()]

    input_payloads = [row.get("payload") for row in rows if str(row.get("name", "")).strip().lower() == "frame.input"]
    ack_payloads = [row.get("payload") for row in rows if str(row.get("name", "")).strip().lower() == "frame.ack"]
    user_e2e_payloads = [row.get("payload") for row in rows if str(row.get("name", "")).strip().lower() == "frame.user_e2e"]

    assert len(input_payloads) == 2
    assert len(ack_payloads) == 2
    assert len(user_e2e_payloads) == 2

    for payload in input_payloads:
        assert isinstance(payload, dict)
        jsonschema.validate(payload, frame_input_schema)
        assert payload.get("schemaVersion") == "frame.input.v1"

    for payload in ack_payloads:
        assert isinstance(payload, dict)
        jsonschema.validate(payload, frame_ack_schema)
        assert payload.get("schemaVersion") == "frame.ack.v1"

    for payload in user_e2e_payloads:
        assert isinstance(payload, dict)
        jsonschema.validate(payload, frame_e2e_schema)
        assert payload.get("schemaVersion") == "frame.e2e.v1"
