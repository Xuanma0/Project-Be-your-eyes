from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")


def test_mode_change_contract_schema_ok() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "Gateway" / "contracts" / "ui.mode_change.v1.json"
    events_path = (
        repo_root
        / "Gateway"
        / "tests"
        / "fixtures"
        / "run_package_with_mode_change_min"
        / "events"
        / "events_v1.jsonl"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    payloads = [row.get("payload") for row in rows if str(row.get("name", "")).strip().lower() == "ui.mode_change"]
    assert len(payloads) == 2
    for payload in payloads:
        assert isinstance(payload, dict)
        jsonschema.validate(payload, schema)
        assert payload.get("schemaVersion") == "ui.mode_change.v1"

