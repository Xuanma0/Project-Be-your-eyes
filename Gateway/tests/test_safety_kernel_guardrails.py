from __future__ import annotations

from byes.safety_kernel import apply_guardrails


def test_critical_guardrails_inject_stop_and_confirm() -> None:
    draft_plan = {
        "schemaVersion": "byes.action_plan.v1",
        "actions": [
            {
                "type": "speak",
                "priority": 1,
                "payload": {"text": "continue"},
                "requiresConfirm": False,
                "blocking": False,
            }
        ],
        "meta": {"safety": {"guardrailsApplied": []}},
    }

    plan2, guardrails, findings = apply_guardrails(draft_plan, risk_level="critical", constraints={"maxActions": 3})

    actions = plan2.get("actions", [])
    assert isinstance(actions, list)
    assert any(str(action.get("type", "")).strip().lower() == "stop" for action in actions)
    for action in actions:
        action_type = str(action.get("type", "")).strip().lower()
        if action_type in {"stop", "confirm"}:
            continue
        assert bool(action.get("requiresConfirm")) is True

    assert guardrails
    assert findings
    safety_meta = plan2.get("meta", {}).get("safety", {})
    assert isinstance(safety_meta.get("guardrailsApplied"), list)
