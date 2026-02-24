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


def test_api_plan_context_endpoint_returns_pack() -> None:
    fixture_name = "run_package_with_plan_context_pack_min"
    with TestClient(app) as client:
        payload = _zip_fixture_bytes(fixture_name)
        response = client.post(
            "/api/run_package/upload",
            files={"file": (f"{fixture_name}.zip", payload, "application/zip")},
            data={"scenarioTag": "plan_context_pack_api_test"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        run_id = str(body["runId"])
        run_dir = Path(body["runDir"])

        ctx_resp = client.get(
            "/api/plan/context",
            params={"runId": run_id, "maxChars": 256, "mode": "seg_plus_pov_plus_risk"},
        )
        assert ctx_resp.status_code == 200, ctx_resp.text
        pack = ctx_resp.json()
        assert pack.get("schemaVersion") == "plan.context_pack.v1"
        assert pack.get("runId")
        assert isinstance(pack.get("budget"), dict)
        prompt = str(pack.get("text", {}).get("prompt", ""))
        assert prompt.strip()

        shutil.rmtree(run_dir, ignore_errors=True)


def test_api_plan_context_endpoint_override_budget() -> None:
    fixture_name = "run_package_with_plan_context_pack_min"
    with TestClient(app) as client:
        payload = _zip_fixture_bytes(fixture_name)
        response = client.post(
            "/api/run_package/upload",
            files={"file": (f"{fixture_name}.zip", payload, "application/zip")},
            data={"scenarioTag": "plan_context_pack_override_test"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        run_id = str(body["runId"])
        run_dir = Path(body["runDir"])

        ctx_resp = client.get(
            "/api/plan/context",
            params={"runId": run_id, "ctxMaxChars": 128, "ctxMode": "risk_only"},
        )
        assert ctx_resp.status_code == 200, ctx_resp.text
        pack = ctx_resp.json()
        assert pack.get("schemaVersion") == "plan.context_pack.v1"
        assert bool(pack.get("budgetOverrideUsed")) is True
        budget = pack.get("budget", {})
        assert isinstance(budget, dict)
        assert int(budget.get("maxChars", 0) or 0) == 128
        assert str(budget.get("mode", "")).strip() == "risk_only"

        shutil.rmtree(run_dir, ignore_errors=True)
