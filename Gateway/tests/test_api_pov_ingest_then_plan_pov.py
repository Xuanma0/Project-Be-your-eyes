from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from main import app
from services.planner_service.app import app as planner_app


def test_api_pov_ingest_then_plan_pov(monkeypatch, tmp_path: Path) -> None:
    fixture_src = Path(__file__).resolve().parent / "fixtures" / "run_package_with_risk_gt_and_pov_min"
    run_pkg = tmp_path / "live_pov_runpkg"
    shutil.copytree(fixture_src, run_pkg)
    events_path = run_pkg / "events" / "events_v1.jsonl"
    pov_path = run_pkg / "pov" / "pov_ir_v1.json"
    pov_payload = json.loads(pov_path.read_text(encoding="utf-8-sig"))
    pov_payload["runId"] = "live-pov-1"

    flask_client = planner_app.test_client()

    class FakeResponse:
        def __init__(self, inner) -> None:
            self._inner = inner
            self.status_code = int(inner.status_code)

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"http status {self.status_code}")

        def json(self):
            return self._inner.get_json()

    class FakeClient:
        def __init__(self, timeout: float = 20.0) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, json: dict | None = None, headers: dict | None = None):
            path = urlparse(url).path or "/plan"
            inner = flask_client.post(path, json=json, headers=headers or {})
            return FakeResponse(inner)

    import byes.planner_backends.http as http_backend

    monkeypatch.setattr(http_backend, "httpx", SimpleNamespace(Client=FakeClient))
    monkeypatch.setenv("BYES_PLANNER_BACKEND", "http")
    monkeypatch.setenv("BYES_PLANNER_ENDPOINT", "http://127.0.0.1:19211/plan")
    monkeypatch.setenv("BYES_PLANNER_PROVIDER", "reference")

    with TestClient(app) as client:
        ingest_response = client.post(
            "/api/pov/ingest",
            params={"runPackage": str(run_pkg)},
            json=pov_payload,
        )
        assert ingest_response.status_code == 200, ingest_response.text
        ingest_data = ingest_response.json()
        assert ingest_data.get("ok") is True
        assert ingest_data.get("runId") == "live-pov-1"
        assert int(ingest_data.get("counts", {}).get("decisions", 0)) >= 2

        plan_response = client.post(
            "/api/plan",
            params={"provider": "pov"},
            json={
                "runPackage": str(run_pkg),
                "runId": "live-pov-1",
                "frameSeq": 2,
                "budget": {"maxChars": 1800, "maxTokensApprox": 256, "mode": "decisions_plus_highlights"},
                "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
            },
        )
        assert plan_response.status_code == 200, plan_response.text
        plan_payload = plan_response.json()

    assert plan_payload.get("schemaVersion") == "byes.action_plan.v1"
    assert str(plan_payload.get("riskLevel", "")).strip().lower() == "critical"
    actions = plan_payload.get("actions", [])
    action_types = {str(action.get("type", "")).strip().lower() for action in actions if isinstance(action, dict)}
    assert {"stop", "confirm", "speak"}.issubset(action_types)
    planner = plan_payload.get("meta", {}).get("planner", {})
    assert planner.get("backend") == "pov"
    assert planner.get("plannerProvider") == "pov"
    assert planner.get("fallbackUsed") is False

    rows = []
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    names = [str(row.get("name", "")).strip().lower() for row in rows if isinstance(row, dict)]
    assert "pov.ingest" in names
    assert "plan.generate" in names
    assert any(
        str(row.get("schemaVersion", "")).strip() == "byes.event.v1"
        and str(row.get("name", "")).strip().lower() == "pov.ingest"
        for row in rows
        if isinstance(row, dict)
    )
