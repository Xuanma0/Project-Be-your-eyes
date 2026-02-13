from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import urlparse

from byes.planner_backends.http import HttpPlannerBackend
from services.planner_service.app import app as planner_app


def _build_request_payload() -> dict:
    return {
        "schemaVersion": "byes.planner_request.v1",
        "runId": "planner-http-test",
        "frameSeq": 1,
        "contextPack": {"schemaVersion": "pov.context.v1"},
        "contextBudget": {"maxChars": 2000, "maxTokensApprox": 256, "mode": "decisions_plus_highlights"},
        "riskSummary": {
            "hazardsTop": [{"hazardKind": "stair_down_edge", "severity": "critical", "score": 0.9}],
            "riskLevel": "critical",
        },
        "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
    }


def test_planner_http_backend_with_test_client(monkeypatch) -> None:
    flask_client = planner_app.test_client()
    direct_response = flask_client.post("/plan", json=_build_request_payload())
    assert direct_response.status_code == 200
    direct_payload = direct_response.get_json()
    assert isinstance(direct_payload, dict)
    assert direct_payload.get("schemaVersion") == "byes.action_plan.v1"
    assert direct_payload.get("meta", {}).get("planner", {}).get("model") == "reference-planner-v1"

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
    monkeypatch.setenv("BYES_PLANNER_ENDPOINT", "http://127.0.0.1:19211/plan")
    backend = HttpPlannerBackend()
    payload = backend.generate_plan(_build_request_payload())

    assert payload.get("schemaVersion") == "byes.action_plan.v1"
    meta = payload.get("meta", {})
    planner = meta.get("planner", {})
    assert planner.get("backend") == "http"
    assert planner.get("model") == "reference-planner-v1"
    assert str(planner.get("endpoint", "")).endswith("/plan")
