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


def test_runs_quality_filter_and_sort() -> None:
    with TestClient(app) as client:
        gt_run_id, gt_dir = _upload(client, "run_package_with_gt_min", "quality_gt_case")
        nongt_run_id, nongt_dir = _upload(client, "run_package_min", "quality_no_gt_case")

        filtered = client.get("/api/run_packages", params={"has_gt": "true", "limit": 100})
        assert filtered.status_code == 200, filtered.text
        items = filtered.json().get("items", [])
        assert any(item.get("runId") == gt_run_id for item in items)
        assert all(bool(item.get("quality_has_gt")) for item in items)
        assert not any(item.get("runId") == nongt_run_id for item in items)

        sorted_resp = client.get("/api/run_packages", params={"sort": "quality", "order": "desc", "limit": 100})
        assert sorted_resp.status_code == 200, sorted_resp.text
        sorted_items = sorted_resp.json().get("items", [])
        assert len(sorted_items) >= 1
        assert sorted_items[0].get("quality_score") is not None

        page = client.get("/runs", params={"has_gt": "true", "sort": "quality", "order": "desc"})
        assert page.status_code == 200, page.text
        assert "Quality" in page.text
        assert "quality_gt_case" in page.text

        shutil.rmtree(gt_dir, ignore_errors=True)
        shutil.rmtree(nongt_dir, ignore_errors=True)
