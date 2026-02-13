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
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            row = json.loads(line)
            names.append(str(row.get("name", "")))
    assert "plan.generate" in names
    assert "safety.kernel" in names
