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


def _upload_run(client: TestClient, scenario: str) -> tuple[str, Path]:
    payload = _build_fixture_zip_bytes()
    response = client.post(
        "/api/run_package/upload",
        files={"file": ("run_package_min.zip", payload, "application/zip")},
        data={"scenarioTag": scenario},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def test_runs_compare_page_ok_and_invalid() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload_run(client, "fixture_compare_a")
        run_b, dir_b = _upload_run(client, "fixture_compare_b")

        ok_resp = client.get(f"/runs/compare?ids={run_a},{run_b}")
        assert ok_resp.status_code == 200, ok_resp.text
        assert "Run Compare" in ok_resp.text
        assert run_a in ok_resp.text
        assert run_b in ok_resp.text

        invalid_resp = client.get("/runs/compare?ids=only_one")
        assert invalid_resp.status_code == 400, invalid_resp.text

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
