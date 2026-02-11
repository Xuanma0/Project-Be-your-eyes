from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def _zip_fixture_bytes(fixture_name: str) -> bytes:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / fixture_name
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in fixture_dir.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(fixture_dir))
    return buffer.getvalue()


def _upload(client: TestClient, fixture_name: str, scenario: str) -> tuple[str, Path]:
    payload = _zip_fixture_bytes(fixture_name)
    response = client.post(
        "/api/run_package/upload",
        files={"file": (f"{fixture_name}.zip", payload, "application/zip")},
        data={"scenarioTag": scenario},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def test_runs_safety_filters_and_columns() -> None:
    with TestClient(app) as client:
        safety_run_id, safety_dir = _upload(client, "run_package_with_safety_events_min", "safety_case")
        clean_run_id, clean_dir = _upload(client, "run_package_with_gt_min", "clean_case")

        rows = client.get("/api/run_packages", params={"has_gt": "true", "sort": "quality", "limit": 100})
        assert rows.status_code == 200, rows.text
        items = rows.json().get("items", [])
        safety_item = next((item for item in items if item.get("runId") == safety_run_id), None)
        assert safety_item is not None
        assert int(safety_item.get("confirm_timeouts", 0)) >= 1
        assert int(safety_item.get("critical_misses", 0)) >= 0

        filtered = client.get("/api/run_packages", params={"has_gt": "true", "max_confirm_timeouts": 0, "limit": 100})
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert not any(item.get("runId") == safety_run_id for item in filtered_items)
        assert any(item.get("runId") == clean_run_id for item in filtered_items)

        page = client.get("/runs", params={"has_gt": "true", "sort": "quality"})
        assert page.status_code == 200, page.text
        assert "ConfirmTimeouts" in page.text
        assert "Critical FN" in page.text
        assert "MaxDelay(fr)" in page.text

        shutil.rmtree(safety_dir, ignore_errors=True)
        shutil.rmtree(clean_dir, ignore_errors=True)
