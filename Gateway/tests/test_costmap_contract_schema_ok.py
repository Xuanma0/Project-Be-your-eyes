from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")


def test_costmap_contract_schema_ok() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "Gateway" / "contracts" / "byes.costmap.v1.json"
    fixture_events = (
        repo_root
        / "Gateway"
        / "tests"
        / "fixtures"
        / "run_package_with_costmap_min"
        / "events"
        / "events_v1.jsonl"
    )

    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    lines = [line for line in fixture_events.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assert lines

    payload = None
    for line in lines:
        event = json.loads(line)
        if str(event.get("name", "")) == "map.costmap":
            payload = event.get("payload")
            break
    assert isinstance(payload, dict)
    jsonschema.validate(payload, schema)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {
                "schemaVersion": "byes.costmap.v1",
                "runId": "bad",
                "frameSeq": 1,
                "frame": "local",
                "grid": {"format": "grid_u8_cost_v1", "size": [4, 4], "resolutionM": 0.1, "dataB64": ""},
                "stats": {
                    "occupiedCells": 1,
                    "meanCost": 10,
                    "maxCost": 255,
                    "dynamicFilteredRate": 2.0,
                    "sources": {"depth": True, "seg": True, "slam": False},
                },
            },
            schema,
        )
