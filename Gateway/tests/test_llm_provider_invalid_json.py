from __future__ import annotations

from services.planner_service.app import app as planner_app


def _request_payload() -> dict:
    return {
        "schemaVersion": "byes.planner_request.v1",
        "runId": "planner-llm-invalid-json-test",
        "frameSeq": 1,
        "contextPack": {"schemaVersion": "pov.context.v1", "text": {"prompt": "walk ahead"}},
        "riskSummary": {
            "hazardsTop": [{"hazardKind": "stair_down_edge", "severity": "critical", "score": 0.9}],
            "riskLevel": "critical",
        },
        "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
    }


class _FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"text": "not json"}


def test_llm_provider_invalid_json_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("BYES_PLANNER_PROVIDER", "llm")
    monkeypatch.setenv("BYES_PLANNER_LLM_ENDPOINT", "http://fake-llm.local/generate")
    monkeypatch.setenv("BYES_PLANNER_PROMPT_VERSION", "v1")

    def _fake_post(*_args, **_kwargs):
        return _FakeResponse()

    monkeypatch.setattr("services.planner_service.app.requests.post", _fake_post)

    client = planner_app.test_client()
    response = client.post("/plan", json=_request_payload())
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)

    planner = payload.get("meta", {}).get("planner", {})
    assert planner.get("plannerProvider") == "llm"
    assert planner.get("fallbackUsed") is True
    assert planner.get("fallbackReason") == "invalid_json"
    assert planner.get("jsonValid") is False
    assert planner.get("model") == "reference-planner-v1"
