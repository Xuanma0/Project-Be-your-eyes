from __future__ import annotations

import io
import json
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


def test_run_packages_export_csv_and_filter_sort() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload_run(client, "leaderboard_alpha")
        run_b, dir_b = _upload_run(client, "leaderboard_beta")

        report_b = dir_b / "report.json"
        payload_b = json.loads(report_b.read_text(encoding="utf-8-sig"))
        payload_b["safemode_enter"] = 2
        payload_b["throttle_enter"] = 3
        report_b.write_text(json.dumps(payload_b, ensure_ascii=False, indent=2), encoding="utf-8")

        csv_resp = client.get("/api/run_packages/export.csv")
        assert csv_resp.status_code == 200, csv_resp.text
        assert "text/csv" in csv_resp.headers.get("content-type", "")
        header = csv_resp.text.splitlines()[0]
        assert "runId" in header and "scenarioTag" in header

        json_resp = client.get("/api/run_packages/export.json", params={"scenario": "alpha"})
        assert json_resp.status_code == 200, json_resp.text
        json_body = json_resp.json()
        items = json_body.get("items", [])
        assert all("alpha" in str(item.get("scenarioTag", "")) for item in items)

        sorted_resp = client.get("/api/run_packages", params={"sort": "safety_score", "order": "asc", "limit": 200})
        assert sorted_resp.status_code == 200, sorted_resp.text
        sorted_items = sorted_resp.json().get("items", [])
        assert len(sorted_items) >= 2
        assert float(sorted_items[0].get("safety_score", 0)) <= float(sorted_items[1].get("safety_score", 0))

        assert any(item.get("runId") == run_a for item in sorted_items)
        assert any(item.get("runId") == run_b for item in sorted_items)

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
