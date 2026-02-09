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


def test_run_package_upload_api_generates_reports() -> None:
    payload = _build_fixture_zip_bytes()
    with TestClient(app) as client:
        response = client.post(
            "/api/run_package/upload",
            files={"file": ("run_package_min.zip", payload, "application/zip")},
            data={"scenarioTag": "fixture_upload"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("ok") is True
        assert isinstance(body.get("runId"), str) and body["runId"]

        run_dir = Path(body["runDir"])
        report_md = Path(body["reportMdPath"])
        report_json = Path(body["reportJsonPath"])
        summary = body.get("summary", {})

        assert run_dir.exists()
        assert report_md.exists()
        assert report_json.exists()
        assert "frame_received" in summary
        assert "frame_completed" in summary
        assert "e2e_count" in summary
        assert "ttfa_count" in summary
        assert "safemode_enter" in summary
        assert "preempt_enter" in summary
        assert "confirm_request" in summary

        shutil.rmtree(run_dir, ignore_errors=True)
