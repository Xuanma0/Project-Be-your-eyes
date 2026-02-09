from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def _build_fixture_zip_bytes() -> bytes:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "run_package_min"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in fixture_dir.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(fixture_dir))
    return buffer.getvalue()


def test_run_packages_index_and_fetch_api() -> None:
    payload = _build_fixture_zip_bytes()
    with TestClient(app) as client:
        upload = client.post(
            "/api/run_package/upload",
            files={"file": ("run_package_min.zip", payload, "application/zip")},
            data={"scenarioTag": "fixture_history"},
        )
        assert upload.status_code == 200, upload.text
        upload_body = upload.json()
        run_id = upload_body.get("runId")
        assert isinstance(run_id, str) and run_id

        list_resp = client.get("/api/run_packages", params={"limit": 20})
        assert list_resp.status_code == 200, list_resp.text
        list_body = list_resp.json()
        assert list_body.get("ok") is True
        items = list_body.get("items", [])
        assert any(item.get("run_id") == run_id for item in items)

        summary_resp = client.get(f"/api/run_packages/{run_id}/summary")
        assert summary_resp.status_code == 200, summary_resp.text
        summary_body = summary_resp.json()
        assert "frame_received" in summary_body
        assert "frame_completed" in summary_body
        assert "e2e_count" in summary_body

        report_resp = client.get(f"/api/run_packages/{run_id}/report")
        assert report_resp.status_code == 200, report_resp.text
        assert "Run Report" in report_resp.text

        zip_resp = client.get(f"/api/run_packages/{run_id}/zip")
        assert zip_resp.status_code == 200, zip_resp.text
        assert zip_resp.headers.get("content-type", "").startswith("application/zip")
        assert len(zip_resp.content) > 0

        run_dir = Path(upload_body["runDir"])
        shutil.rmtree(run_dir, ignore_errors=True)
