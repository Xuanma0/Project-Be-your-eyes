from __future__ import annotations

import json
from pathlib import Path

from services.planner_service.app import app as planner_app


def test_pov_provider_inline_pov_ir(monkeypatch) -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "pov_ir_v1_min" / "pov" / "pov_ir_v1.json"
    pov_ir = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    pov_ir["runId"] = "inline-pov-plan-1"

    monkeypatch.setenv("BYES_PLANNER_PROVIDER", "reference")
    client = planner_app.test_client()
    response = client.post(
        "/plan",
        json={
            "schemaVersion": "byes.planner_request.v1",
            "provider": "pov",
            "runId": "inline-pov-plan-1",
            "frameSeq": 1,
            "contextPack": {"schemaVersion": "pov.context.v1"},
            "contextBudget": {"maxChars": 2000, "maxTokensApprox": 256, "mode": "decisions_plus_highlights"},
            "riskSummary": {"hazardsTop": []},
            "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
            "povIr": pov_ir,
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
