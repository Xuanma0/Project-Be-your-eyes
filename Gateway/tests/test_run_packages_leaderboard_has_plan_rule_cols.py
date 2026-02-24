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


def test_run_packages_leaderboard_has_plan_rule_cols() -> None:
    with TestClient(app) as client:
        payload = _zip_fixture_bytes("run_package_min")
        response = client.post(
            "/api/run_package/upload",
            files={"file": ("plan_rule_cols.zip", payload, "application/zip")},
            data={"scenarioTag": "plan_rule_cols"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        run_dir = Path(body["runDir"])

        report_path = run_dir / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        report["planEval"] = {"present": True, "ruleAppliedCount": 1, "ruleHazardHintTop": "stairs_or_dropoff"}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        rows = client.get("/api/run_packages", params={"limit": 100})
        assert rows.status_code == 200, rows.text
        items = rows.json().get("items", [])
        row = next((item for item in items if item.get("runId") == body["runId"]), None)
        assert isinstance(row, dict)
        assert "plan_rule_applied" in row
        assert "plan_rule_hint" in row

        filtered = client.get("/api/run_packages", params={"max_plan_req_seg_trunc_dropped": 0, "limit": 100})
        assert filtered.status_code == 200, filtered.text

        shutil.rmtree(run_dir, ignore_errors=True)
