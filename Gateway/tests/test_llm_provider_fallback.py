from __future__ import annotations

import requests

from services.planner_service.app import app as planner_app


def _request_payload() -> dict:
    return {
        "schemaVersion": "byes.planner_request.v1",
        "runId": "planner-llm-timeout-test",
        "frameSeq": 1,
        "contextPack": {"schemaVersion": "pov.context.v1", "text": {"prompt": "walk ahead"}},
        "riskSummary": {
            "hazardsTop": [{"hazardKind": "stair_down_edge", "severity": "critical", "score": 0.9}],
            "riskLevel": "critical",
        },
        "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
    }


def test_llm_provider_timeout_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("BYES_PLANNER_PROVIDER", "llm")
    monkeypatch.setenv("BYES_PLANNER_LLM_ENDPOINT", "http://fake-llm.local/generate")
    monkeypatch.setenv("BYES_PLANNER_PROMPT_VERSION", "v1")

    def _raise_timeout(*_args, **_kwargs):
        raise requests.Timeout("timeout")

    monkeypatch.setattr("services.planner_service.app.requests.post", _raise_timeout)

    client = planner_app.test_client()
    response = client.post("/plan", json=_request_payload())
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)

    planner = payload.get("meta", {}).get("planner", {})
    assert planner.get("plannerProvider") == "llm"
    assert planner.get("fallbackUsed") is True
    assert planner.get("fallbackReason") == "timeout"
    assert planner.get("jsonValid") is False
    assert planner.get("model") == "reference-planner-v1"
