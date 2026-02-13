from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from main import app
from services.planner_service.app import app as planner_app


def test_api_plan_http_path(monkeypatch, tmp_path: Path) -> None:
    fixture_src = Path(__file__).resolve().parent / "fixtures" / "run_package_with_risk_gt_and_pov_min"
    run_pkg = tmp_path / "plan_http_runpkg"
    shutil.copytree(fixture_src, run_pkg)

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

    with TestClient(app) as client:
        response = client.post(
            "/api/plan",
            json={
                "runPackage": str(run_pkg),
                "frameSeq": 2,
                "budget": {"maxChars": 1800, "maxTokensApprox": 256, "mode": "decisions_plus_highlights"},
                "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()

    planner = payload.get("meta", {}).get("planner", {})
    assert planner.get("backend") == "http"
    assert planner.get("model") == "reference-planner-v1"
    guardrails = payload.get("meta", {}).get("safety", {}).get("guardrailsApplied", [])
    assert "critical_inject_stop" in guardrails
    actions = payload.get("actions", [])
    assert any(str(action.get("type", "")).strip().lower() == "stop" for action in actions)
