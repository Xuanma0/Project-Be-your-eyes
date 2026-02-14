from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_api_contracts_endpoint_returns_lock_and_runtime_defaults() -> None:
    with TestClient(app) as client:
        response = client.get("/api/contracts")
        assert response.status_code == 200, response.text
        payload = response.json()

    versions = payload.get("versions", {})
    assert isinstance(versions, dict)
    for key in ("pov.ir.v1", "byes.event.v1", "byes.action_plan.v1", "byes.seg.v1", "byes.seg_request.v1"):
        assert key in versions
        row = versions[key]
        assert isinstance(row, dict)
        sha256 = str(row.get("sha256", ""))
        assert len(sha256) == 64

    runtime_defaults = payload.get("runtimeDefaults", {})
    assert isinstance(runtime_defaults, dict)
    pov_context = runtime_defaults.get("povContext", {})
    assert isinstance(pov_context, dict)
    default_budget = pov_context.get("defaultBudget", {})
    assert isinstance(default_budget, dict)
    assert int(default_budget.get("maxTokensApprox", 0)) > 0
    seg_prompt = runtime_defaults.get("segPrompt", {})
    assert isinstance(seg_prompt, dict)
    assert "promptPresent" in seg_prompt
