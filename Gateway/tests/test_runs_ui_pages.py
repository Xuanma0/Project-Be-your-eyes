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


def test_runs_pages_render() -> None:
    payload = _build_fixture_zip_bytes()
    with TestClient(app) as client:
        upload = client.post(
            "/api/run_package/upload",
            files={"file": ("run_package_min.zip", payload, "application/zip")},
            data={"scenarioTag": "fixture_runs_ui"},
        )
        assert upload.status_code == 200, upload.text
        body = upload.json()
        run_id = body["runId"]

        dashboard = client.get("/runs")
        assert dashboard.status_code == 200, dashboard.text
        assert "Run Packages" in dashboard.text

        details = client.get(f"/runs/{run_id}")
        assert details.status_code == 200, details.text
        assert run_id in details.text

        run_dir = Path(body["runDir"])
        shutil.rmtree(run_dir, ignore_errors=True)
