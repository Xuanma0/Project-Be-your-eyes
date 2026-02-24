from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")


def test_seg_contract_schema_ok_trackid() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "Gateway" / "contracts" / "byes.seg.v1.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))

    valid_payload = {
        "segments": [
            {
                "label": "person",
                "score": 0.9,
                "bbox": [0, 0, 4, 4],
                "trackId": "trk-1",
                "trackState": "track",
            }
        ]
    }
    jsonschema.validate(valid_payload, schema)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {
                "segments": [
                    {"label": "person", "score": 0.9, "bbox": [0, 0, 4, 4], "trackId": "", "trackState": "track"}
                ]
            },
            schema,
        )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {
                "segments": [
                    {
                        "label": "person",
                        "score": 0.9,
                        "bbox": [0, 0, 4, 4],
                        "trackId": "trk-1",
                        "trackState": "unknown",
                    }
                ]
            },
            schema,
        )
