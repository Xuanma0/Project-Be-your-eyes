from __future__ import annotations

from byes.plan_eval import compute_plan_eval


def test_plan_eval_metrics_confirm_timeout_and_guardrail() -> None:
    events = [
        {
            "schemaVersion": "byes.event.v1",
            "name": "plan.generate",
            "phase": "result",
            "status": "ok",
            "latencyMs": 120,
            "payload": {
                "riskLevel": "critical",
                "actionsCount": 3,
                "stopCount": 1,
                "confirmActionCount": 1,
                "blockingCount": 2,
            },
        },
        {
            "schemaVersion": "byes.event.v1",
            "name": "plan.execute",
            "phase": "result",
            "status": "ok",
            "latencyMs": 80,
            "payload": {"executedCount": 2, "blockedCount": 0, "pendingConfirmCount": 1},
        },
        {
            "schemaVersion": "byes.event.v1",
            "name": "ui.confirm_request",
            "phase": "start",
            "status": "ok",
            "payload": {"confirmId": "c1"},
        },
    ]
    report = {
        "plan": {
            "present": True,
            "riskLevel": "critical",
            "actions": {
                "count": 3,
                "types": ["stop", "confirm", "speak"],
                "stopCount": 1,
                "confirmActionCount": 1,
                "blockingCount": 2,
            },
            "guardrailsApplied": ["critical_inject_stop", "critical_force_requires_confirm"],
        }
    }

    out = compute_plan_eval(events, report)
    assert out["present"] is True
    assert out["latencyMs"]["p90"] == 120
    assert out["executeLatencyMs"]["p90"] == 80
    assert out["confirm"]["requests"] == 1
    assert out["confirm"]["responses"] == 0
    assert out["confirm"]["timeouts"] == 1
    assert out["confirm"]["pending"] == 1
    assert out["actions"]["stopCount"] == 1
    assert out["actions"]["blockingCount"] == 2
    assert out["guardrails"]["appliedCount"] == 2
    assert out["guardrails"]["overrideRate"] > 0


def test_plan_eval_overcautious_when_not_critical() -> None:
    events = [
        {
            "schemaVersion": "byes.event.v1",
            "name": "plan.generate",
            "phase": "result",
            "status": "ok",
            "latencyMs": 50,
            "payload": {"riskLevel": "medium"},
        }
    ]
    report = {
        "plan": {
            "present": True,
            "riskLevel": "medium",
            "actions": {
                "count": 2,
                "types": ["stop", "confirm"],
                "stopCount": 1,
                "confirmActionCount": 1,
                "blockingCount": 1,
            },
            "guardrailsApplied": [],
        }
    }

    out = compute_plan_eval(events, report)
    assert out["overcautious"]["stopWhenNotCritical"] == 1
    assert out["overcautious"]["confirmWhenNotCritical"] == 1
    assert out["overcautious"]["rate"] == 1.0
