from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def load_schema() -> dict[str, Any]:
    schema_path = _find_schema_path()
    payload = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"schema must be json object: {schema_path}")
    return payload


def validate_pov_ir(obj: Any, strict: bool = True) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, ["payload must be object"]

    schema = load_schema()
    validator = Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(obj), key=lambda item: list(item.path))
    for item in schema_errors:
        path = "/".join(str(part) for part in item.path)
        at = f"/{path}" if path else "/"
        errors.append(f"{at}: {item.message}")

    _validate_decision_point_ordering(obj, errors)
    ok = not errors
    if strict:
        return ok, errors
    return True, errors


def _validate_decision_point_ordering(obj: dict[str, Any], errors: list[str]) -> None:
    rows = obj.get("decisionPoints")
    if not isinstance(rows, list):
        return
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        t0 = _as_int(row.get("t0Ms"))
        t1 = _as_int(row.get("t1Ms"))
        if t0 is None or t1 is None:
            continue
        if t1 < t0:
            errors.append(f"/decisionPoints/{idx}/t1Ms: must be >= t0Ms")


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _find_schema_path() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "schemas" / "pov_ir_v1.schema.json"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("schemas/pov_ir_v1.schema.json not found")
