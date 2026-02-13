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


def test_runs_pov_filters_and_sort() -> None:
    with TestClient(app) as client:
        pov_run_id, pov_dir = _upload(client, "pov_ir_v1_min", "pov_filter_has_pov")
        no_pov_run_id, no_pov_dir = _upload(client, "run_package_min", "pov_filter_no_pov")

        has_pov_resp = client.get("/api/run_packages", params={"has_pov": "true", "limit": 100})
        assert has_pov_resp.status_code == 200, has_pov_resp.text
        items = has_pov_resp.json().get("items", [])
        pov_row = next((item for item in items if item.get("runId") == pov_run_id), None)
        assert pov_row is not None
        assert bool(pov_row.get("pov_present")) is True
        assert int(pov_row.get("pov_decisions", 0)) >= 2
        assert not any(item.get("runId") == no_pov_run_id for item in items)

        sorted_resp = client.get("/api/run_packages", params={"sort": "pov_decisions", "order": "desc", "limit": 100})
        assert sorted_resp.status_code == 200, sorted_resp.text
        sorted_items = sorted_resp.json().get("items", [])
        pov_sorted = next((item for item in sorted_items if item.get("runId") == pov_run_id), None)
        no_pov_sorted = next((item for item in sorted_items if item.get("runId") == no_pov_run_id), None)
        assert pov_sorted is not None
        assert no_pov_sorted is not None
        assert int(pov_sorted.get("pov_decisions", 0)) >= int(no_pov_sorted.get("pov_decisions", 0))
        assert sorted_items.index(pov_sorted) < sorted_items.index(no_pov_sorted)

        html_page = client.get("/runs", params={"has_pov": "true", "sort": "pov_decisions"})
        assert html_page.status_code == 200, html_page.text
        assert "POV Decisions" in html_page.text

        shutil.rmtree(pov_dir, ignore_errors=True)
        shutil.rmtree(no_pov_dir, ignore_errors=True)
