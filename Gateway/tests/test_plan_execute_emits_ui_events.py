from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def _make_run_package(root: Path) -> Path:
    run_pkg = root / "runpkg"
    (run_pkg / "events").mkdir(parents=True, exist_ok=True)
    manifest = {
        "runId": "plan-exec-run",
        "eventsV1Jsonl": "events/events_v1.jsonl",
    }
    (run_pkg / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_pkg / "events" / "events_v1.jsonl").write_text("", encoding="utf-8")
    return run_pkg


def test_plan_execute_emits_ui_events(tmp_path: Path) -> None:
    run_pkg = _make_run_package(tmp_path)
    plan = {
        "schemaVersion": "byes.action_plan.v1",
        "runId": "plan-exec-run",
        "frameSeq": 1,
        "generatedAtMs": 1000,
        "intent": "assist_navigation",
        "riskLevel": "critical",
        "ttlMs": 2000,
        "actions": [
            {
                "type": "confirm",
                "priority": 0,
                "payload": {"confirmId": "c-1", "text": "Stop now?", "timeoutMs": 3000},
                "requiresConfirm": False,
                "blocking": False,
            },
            {
                "type": "speak",
                "priority": 1,
                "payload": {"text": "Please slow down."},
                "requiresConfirm": True,
                "blocking": False,
            },
        ],
        "meta": {
            "planner": {"backend": "mock", "model": "mock-planner-v1", "endpoint": None},
            "budget": {"contextMaxTokensApprox": 256, "contextMaxChars": 2000, "mode": "decisions_plus_highlights"},
            "safety": {"guardrailsApplied": []},
        },
    }

    with TestClient(app) as client:
        resp = client.post(
            "/api/plan/execute",
            json={
                "plan": plan,
                "runPackage": str(run_pkg),
                "runId": "plan-exec-run",
                "frameSeq": 1,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert int(body.get("executedCount", 0)) >= 2
        assert int(body.get("pendingConfirmCount", 0)) == 1

    events_path = run_pkg / "events" / "events_v1.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    names = [str(row.get("name", "")) for row in rows]
    assert "plan.execute" in names
    assert "ui.confirm_request" in names
    assert "ui.command" in names

    speak_rows = [row for row in rows if str(row.get("name", "")) == "ui.command"]
    assert speak_rows
    payload = speak_rows[-1].get("payload", {})
    assert str(payload.get("commandType", "")).strip().lower() == "speak"
