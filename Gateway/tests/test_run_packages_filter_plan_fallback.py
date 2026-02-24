from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def _zip_dir_bytes(path: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in path.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(path))
    return buffer.getvalue()


def _upload_dir(client: TestClient, path: Path, scenario: str) -> tuple[str, Path]:
    payload = _zip_dir_bytes(path)
    response = client.post(
        "/api/run_package/upload",
        files={"file": (f"{path.name}.zip", payload, "application/zip")},
        data={"scenarioTag": scenario},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_fallback_flag(events_path: Path, enabled: bool) -> None:
    rows = []
    for raw in events_path.read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        if str(row.get("name", "")).strip().lower() == "plan.generate":
            payload = row.get("payload", {})
            payload = payload if isinstance(payload, dict) else {}
            payload["fallbackUsed"] = bool(enabled)
            payload["fallbackReason"] = "timeout" if enabled else None
            payload["jsonValid"] = False if enabled else True
            row["payload"] = payload
        rows.append(row)
    events_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_run_packages_filter_plan_fallback(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "run_package_with_plan_llm_stub_min"
    true_pkg = tmp_path / "fallback_true"
    false_pkg = tmp_path / "fallback_false"
    shutil.copytree(fixture, true_pkg)
    shutil.copytree(fixture, false_pkg)

    _set_fallback_flag(true_pkg / "events" / "events_v1.jsonl", enabled=True)
    _set_fallback_flag(false_pkg / "events" / "events_v1.jsonl", enabled=False)

    with TestClient(app) as client:
        true_run_id, true_run_dir = _upload_dir(client, true_pkg, "plan_fallback_true")
        false_run_id, false_run_dir = _upload_dir(client, false_pkg, "plan_fallback_false")

        response_true = client.get("/api/run_packages", params={"plan_fallback_used": "true", "limit": 100})
        assert response_true.status_code == 200, response_true.text
        rows_true = response_true.json().get("items", [])
        assert any(row.get("runId") == true_run_id for row in rows_true)
        assert not any(row.get("runId") == false_run_id for row in rows_true)
        target_true = next((row for row in rows_true if row.get("runId") == true_run_id), None)
        assert isinstance(target_true, dict)
        assert "plan_fallback_used" in target_true

        response_false = client.get("/api/run_packages", params={"plan_fallback_used": "false", "limit": 100})
        assert response_false.status_code == 200, response_false.text
        rows_false = response_false.json().get("items", [])
        assert any(row.get("runId") == false_run_id for row in rows_false)

        shutil.rmtree(true_run_dir, ignore_errors=True)
        shutil.rmtree(false_run_dir, ignore_errors=True)
