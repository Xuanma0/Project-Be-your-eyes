from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")


def test_costmap_fused_contract_schema_ok() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "Gateway" / "contracts" / "byes.costmap_fused.v1.json"
    fixture_events = (
        repo_root
        / "Gateway"
        / "tests"
        / "fixtures"
        / "run_package_with_costmap_fused_min"
        / "events"
        / "events_v1.jsonl"
    )

    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    lines = [line for line in fixture_events.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assert lines

    payload = None
    for line in lines:
        event = json.loads(line)
        if str(event.get("name", "")) == "map.costmap_fused":
            payload = event.get("payload")
            break
    assert isinstance(payload, dict)
    jsonschema.validate(payload, schema)
