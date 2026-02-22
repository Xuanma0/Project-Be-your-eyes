from __future__ import annotations

import json
from pathlib import Path

try:
    import jsonschema
except Exception:  # noqa: BLE001
    jsonschema = None

from byes.config import load_config
from byes.model_manifest import build_model_manifest


def test_models_contract_schema_ok() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "Gateway" / "contracts" / "byes.models.v1.json"
    lock_path = repo_root / "Gateway" / "contracts" / "contract.lock.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    assert isinstance(schema, dict)
    assert schema.get("$id") == "byes.models.v1"

    lock_payload = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    versions = lock_payload.get("versions", {})
    assert isinstance(versions, dict)
    assert "byes.models.v1" in versions

    manifest = build_model_manifest(load_config())
    assert manifest.get("schemaVersion") == "byes.models.v1"
    if jsonschema is not None:
        jsonschema.validate(instance=manifest, schema=schema)


def test_models_manifest_seg_sam3_required_ckpt(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("BYES_ENABLE_SEG", "1")
    monkeypatch.setenv("BYES_SEG_BACKEND", "http")
    monkeypatch.setenv("BYES_SEG_HTTP_URL", "http://127.0.0.1:19271/seg")
    monkeypatch.setenv("BYES_SERVICE_SEG_HTTP_DOWNSTREAM", "sam3")
    monkeypatch.delenv("BYES_SAM3_CKPT_PATH", raising=False)

    manifest = build_model_manifest(load_config())
    components = manifest.get("components")
    assert isinstance(components, list)
    seg = next(
        (item for item in components if isinstance(item, dict) and str(item.get("name", "")).strip() == "seg"),
        None,
    )
    assert isinstance(seg, dict)
    required = seg.get("required")
    assert isinstance(required, list)
    sam3_req = next((row for row in required if isinstance(row, dict) and row.get("id") == "sam3_ckpt_path"), None)
    assert isinstance(sam3_req, dict)
    assert bool(sam3_req.get("exists")) is False
