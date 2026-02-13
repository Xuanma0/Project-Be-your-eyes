from __future__ import annotations

import json
from pathlib import Path

from services.planner_service.app import app as planner_app


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "pov_plan_min"


def _load_expected() -> dict:
    path = _fixture_dir() / "expected" / "plan_action_plan_v1.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _normalize_plan(plan: dict) -> dict:
    payload = json.loads(json.dumps(plan))
    payload["generatedAtMs"] = 0
    return payload


def test_planner_pov_provider_matches_expected(monkeypatch) -> None:
    fixture_dir = _fixture_dir()
    expected = _load_expected()

    monkeypatch.setenv("BYES_PLANNER_PROVIDER", "pov")
    client = planner_app.test_client()
    response = client.post(
        "/plan",
        json={
            "schemaVersion": "byes.planner_request.v1",
            "runId": "fixture-pov-plan-min",
            "frameSeq": 1,
            "contextPack": {"schemaVersion": "pov.context.v1"},
            "contextBudget": {"maxChars": 2000, "maxTokensApprox": 256, "mode": "decisions_plus_highlights"},
            "riskSummary": {"hazardsTop": []},
            "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
            "runPackagePath": str(fixture_dir),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert payload.get("schemaVersion") == "byes.action_plan.v1"

    planner = payload.get("meta", {}).get("planner", {})
    assert planner.get("backend") == "pov"
    assert planner.get("model") == "pov-ir-v1"
    assert planner.get("plannerProvider") == "pov"
    assert planner.get("fallbackUsed") is False
    assert planner.get("jsonValid") is True

    assert _normalize_plan(payload) == expected
