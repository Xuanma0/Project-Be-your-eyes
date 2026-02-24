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


def test_runs_filters_plan_score() -> None:
    with TestClient(app) as client:
        plan_run_id, plan_dir = _upload(client, "run_package_with_risk_gt_and_pov_min", "plan_score_has")
        no_plan_run_id, no_plan_dir = _upload(client, "run_package_min", "plan_score_none")

        by_score = client.get(
            "/api/run_packages",
            params={"has_plan": "true", "sort": "plan_score", "order": "desc", "limit": 100},
        )
        assert by_score.status_code == 200, by_score.text
        items = by_score.json().get("items", [])
        plan_row = next((item for item in items if item.get("runId") == plan_run_id), None)
        assert plan_row is not None
        assert "plan_score" in plan_row
        assert "plan_has_stop" in plan_row
        assert "plan_has_confirm" in plan_row

        min_score = client.get(
            "/api/run_packages",
            params={"min_plan_score": 1, "limit": 100},
        )
        assert min_score.status_code == 200, min_score.text
        min_score_items = min_score.json().get("items", [])
        assert any(item.get("runId") == plan_run_id for item in min_score_items)
        assert not any(item.get("runId") == no_plan_run_id for item in min_score_items)

        critical_only = client.get(
            "/api/run_packages",
            params={"has_plan": "true", "plan_risk_level": "critical", "limit": 100},
        )
        assert critical_only.status_code == 200, critical_only.text
        critical_items = critical_only.json().get("items", [])
        assert any(item.get("runId") == plan_run_id for item in critical_items)

        shutil.rmtree(plan_dir, ignore_errors=True)
        shutil.rmtree(no_plan_dir, ignore_errors=True)
