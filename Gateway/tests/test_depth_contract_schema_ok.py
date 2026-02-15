from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")


def test_depth_contract_schema_ok() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "Gateway" / "contracts" / "byes.depth.v1.json"
    fixture_events = (
        repo_root
        / "Gateway"
        / "tests"
        / "fixtures"
        / "run_package_with_depth_gt_min"
        / "events"
        / "events_v1.jsonl"
    )

    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    lines = [line for line in fixture_events.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assert lines
    first_event = json.loads(lines[0])
    payload = first_event.get("payload", {})
    assert isinstance(payload, dict)
    jsonschema.validate(payload, schema)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {
                "grid": {
                    "format": "grid_u16_mm_v1",
                    "size": [2, 2],
                    "unit": "mm",
                    "values": [0, 1, 2, 70000],
                }
            },
            schema,
        )

