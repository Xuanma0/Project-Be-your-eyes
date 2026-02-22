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
    for key in (
        "pov.ir.v1",
        "byes.event.v1",
        "byes.action_plan.v1",
        "byes.depth.v1",
        "byes.ocr.v1",
        "byes.slam_pose.v1",
        "byes.seg.v1",
        "byes.seg_request.v1",
        "seg.context.v1",
        "byes.plan_request.v1",
        "plan.context_alignment.v1",
        "plan.context_pack.v1",
        "frame.e2e.v1",
        "byes.models.v1",
    ):
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
    default_budget = seg_prompt.get("defaultBudget", {})
    assert isinstance(default_budget, dict)
    assert int(default_budget.get("maxChars", 0)) > 0
    assert int(default_budget.get("maxTargets", 0)) > 0
    seg_context = runtime_defaults.get("segContext", {})
    assert isinstance(seg_context, dict)
    seg_ctx_budget = seg_context.get("defaultBudget", {})
    assert isinstance(seg_ctx_budget, dict)
    assert int(seg_ctx_budget.get("maxChars", 0)) > 0
    assert int(seg_ctx_budget.get("maxSegments", 0)) > 0
    plan_request = runtime_defaults.get("planRequest", {})
    assert isinstance(plan_request, dict)
    assert str(plan_request.get("defaultPromptVersion", "")).strip()
    assert "includeSegContext" in plan_request
    assert "includePovContext" in plan_request
    plan_context_pack = runtime_defaults.get("planContextPack", {})
    assert isinstance(plan_context_pack, dict)
    plan_context_budget = plan_context_pack.get("defaultBudget", {})
    assert isinstance(plan_context_budget, dict)
    assert int(plan_context_budget.get("maxChars", 0)) > 0
    assert str(plan_context_budget.get("mode", "")).strip()
    models_defaults = runtime_defaults.get("models", {})
    assert isinstance(models_defaults, dict)
    assert str(models_defaults.get("checkScript", "")).strip()
