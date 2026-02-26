from __future__ import annotations

from services.planner_service.app import app as planner_app


def _request_payload() -> dict:
    return {
        "schemaVersion": "byes.planner_request.v1",
        "runId": "planner-openai-key-compat-test",
        "frameSeq": 1,
        "contextPack": {"schemaVersion": "pov.context.v1", "text": {"prompt": "walk ahead"}},
        "riskSummary": {"riskLevel": "warn"},
        "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
    }


class _FakeOpenAIResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"schemaVersion":"byes.action_plan.v1","riskLevel":"warn",'
                            '"actions":[{"type":"speak","priority":1,"payload":{"text":"ok"},'
                            '"requiresConfirm":false,"blocking":false}]}'
                        )
                    }
                }
            ]
        }


def test_llm_openai_mode_accepts_openai_api_key_fallback(monkeypatch) -> None:
    monkeypatch.setenv("BYES_PLANNER_PROVIDER", "llm")
    monkeypatch.setenv("BYES_PLANNER_LLM_MODE", "openai")
    monkeypatch.setenv("BYES_PLANNER_LLM_ENDPOINT", "http://fake-openai.local/v1/chat/completions")
    monkeypatch.delenv("BYES_PLANNER_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-openai-key")

    captured = {"auth": ""}

    def _fake_post(*_args, **kwargs):
        headers = kwargs.get("headers") if isinstance(kwargs, dict) else None
        if isinstance(headers, dict):
            captured["auth"] = str(headers.get("Authorization", ""))
        return _FakeOpenAIResponse()

    monkeypatch.setattr("services.planner_service.app.requests.post", _fake_post)

    client = planner_app.test_client()
    response = client.post("/plan", json=_request_payload())
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)

    planner = payload.get("meta", {}).get("planner", {})
    assert planner.get("plannerProvider") == "llm"
    assert planner.get("fallbackUsed") is False
    assert planner.get("jsonValid") is True
    assert captured["auth"] == "Bearer fallback-openai-key"
