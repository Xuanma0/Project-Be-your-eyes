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


def test_runs_filters_has_plan() -> None:
    with TestClient(app) as client:
        plan_run_id, plan_dir = _upload(client, "run_package_with_risk_gt_and_pov_min", "plan_has")
        no_plan_run_id, no_plan_dir = _upload(client, "run_package_min", "plan_none")

        filtered = client.get("/api/run_packages", params={"has_plan": "true", "limit": 100})
        assert filtered.status_code == 200, filtered.text
        items = filtered.json().get("items", [])
        assert any(item.get("runId") == plan_run_id for item in items)
        assert not any(item.get("runId") == no_plan_run_id for item in items)

        plan_row = next((item for item in items if item.get("runId") == plan_run_id), None)
        assert plan_row is not None
        assert "plan_risk_level" in plan_row
        assert "plan_actions" in plan_row
        assert "plan_guardrails" in plan_row

        zero_guard = client.get(
            "/api/run_packages",
            params={"has_plan": "true", "max_plan_guardrails": 0, "limit": 100},
        )
        assert zero_guard.status_code == 200, zero_guard.text
        zero_guard_items = zero_guard.json().get("items", [])
        assert not any(item.get("runId") == plan_run_id for item in zero_guard_items)

        page = client.get("/runs", params={"has_plan": "true"})
        assert page.status_code == 200, page.text
        assert "Plan Guardrails" in page.text

        shutil.rmtree(plan_dir, ignore_errors=True)
        shutil.rmtree(no_plan_dir, ignore_errors=True)
