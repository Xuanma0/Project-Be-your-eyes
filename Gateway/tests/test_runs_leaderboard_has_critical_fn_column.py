from __future__ import annotations

import io
import json
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


def test_runs_leaderboard_includes_miss_critical_count_field() -> None:
    with TestClient(app) as client:
        payload = _zip_fixture_bytes("run_package_min")
        upload = client.post(
            "/api/run_package/upload",
            files={"file": ("run_package_min.zip", payload, "application/zip")},
            data={"scenarioTag": "critical_fn_column_case"},
        )
        assert upload.status_code == 200, upload.text
        body = upload.json()
        run_id = str(body["runId"])
        run_dir = Path(body["runDir"])

        report_path = run_dir / "report.json"
        report_payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
        quality = report_payload.get("quality")
        if not isinstance(quality, dict):
            quality = {}
        depth_risk = quality.get("depthRisk")
        if not isinstance(depth_risk, dict):
            depth_risk = {}
        critical = depth_risk.get("critical")
        if not isinstance(critical, dict):
            critical = {}
        critical["missCriticalCount"] = 3
        depth_risk["critical"] = critical
        quality["depthRisk"] = depth_risk
        report_payload["quality"] = quality
        report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        resp = client.get("/api/run_packages", params={"limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        row = next((item for item in items if item.get("runId") == run_id), None)
        assert row is not None
        assert int(row.get("missCriticalCount", 0)) == 3

        page = client.get("/runs")
        assert page.status_code == 200, page.text
        assert "Critical FN" in page.text

        shutil.rmtree(run_dir, ignore_errors=True)
