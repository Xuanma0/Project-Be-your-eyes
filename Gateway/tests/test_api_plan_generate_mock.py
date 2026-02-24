from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def test_api_plan_generate_mock_with_guardrails_and_events(tmp_path: Path) -> None:
    fixture_src = Path(__file__).resolve().parent / "fixtures" / "run_package_with_risk_gt_and_pov_min"
    run_pkg = tmp_path / "plan_runpkg"
    shutil.copytree(fixture_src, run_pkg)
    events_path = run_pkg / "events" / "events_v1.jsonl"

    with TestClient(app) as client:
        response = client.post(
            "/api/plan",
            json={
                "runPackage": str(run_pkg),
                "frameSeq": 2,
                "budget": {"maxChars": 1800, "maxTokensApprox": 256, "mode": "decisions_plus_highlights"},
                "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
                "contextPackOverride": {"maxChars": 128, "mode": "risk_only"},
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()

    assert payload.get("schemaVersion") == "byes.action_plan.v1"
    assert str(payload.get("riskLevel", "")).strip().lower() == "critical"
    actions = payload.get("actions", [])
    assert isinstance(actions, list)
    assert len(actions) <= 3
    assert any(str(action.get("type", "")).strip().lower() == "stop" for action in actions)
    guardrails = payload.get("meta", {}).get("safety", {}).get("guardrailsApplied", [])
    assert isinstance(guardrails, list) and guardrails

    names: list[str] = []
    plan_context_pack_budget: dict[str, object] | None = None
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            row = json.loads(line)
            names.append(str(row.get("name", "")))
            if str(row.get("name", "")).strip().lower() == "plan.context_pack":
                payload_raw = row.get("payload")
                payload_raw = payload_raw if isinstance(payload_raw, dict) else {}
                budget_raw = payload_raw.get("budget")
                budget_raw = budget_raw if isinstance(budget_raw, dict) else {}
                plan_context_pack_budget = budget_raw
    assert "plan.generate" in names
    assert "safety.kernel" in names
    assert "plan.context_pack" in names
    assert isinstance(plan_context_pack_budget, dict)
    assert int(plan_context_pack_budget.get("maxChars", 0) or 0) == 128
    assert str(plan_context_pack_budget.get("mode", "")).strip() == "risk_only"
