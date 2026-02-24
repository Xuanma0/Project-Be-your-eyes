from __future__ import annotations

import json
from pathlib import Path

from byes.schemas.pov_ir_schema import validate_pov_ir


def test_pov_ir_schema_validation_fixture_ok() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "pov_ir_v1_min" / "pov" / "pov_ir_v1.json"
    payload = json.loads(fixture.read_text(encoding="utf-8-sig"))
    ok, errors = validate_pov_ir(payload, strict=True)
    assert ok is True
    assert errors == []
