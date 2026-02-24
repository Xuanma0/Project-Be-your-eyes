from __future__ import annotations

from services.planner_service.app import app as planner_app


def test_reference_planner_seg_hint_rules_stairs() -> None:
    client = planner_app.test_client()
    response = client.post(
        "/plan",
        json={
            "schemaVersion": "byes.plan_request.v1",
            "runId": "fixture-plan-request-seg-hint",
            "frameSeq": 1,
            "risk": {"riskLevel": "critical", "hazardsCount": 1},
            "contexts": {
                "pov": {
                    "included": True,
                    "promptFragment": "POV context",
                    "chars": 11,
                    "tokenApprox": 3,
                    "truncation": {"dropped": 0}
                },
                "seg": {
                    "included": True,
                    "promptFragment": "person near stairs and curb edge",
                    "chars": 32,
                    "tokenApprox": 8,
                    "truncation": {"segmentsDropped": 0, "charsDropped": 0}
                }
            },
            "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
            "meta": {"provider": "reference", "promptVersion": "v2"}
        },
    )
    assert response.status_code == 200, response.text
    payload = response.get_json()
    actions = payload.get("actions", []) if isinstance(payload.get("actions"), list) else []
    speak_texts = [str((row.get("payload") or {}).get("text", "")) for row in actions if str(row.get("type", "")).lower() == "speak"]
    confirm_texts = [str((row.get("payload") or {}).get("text", "")) for row in actions if str(row.get("type", "")).lower() == "confirm"]
    assert any("Possible stairs or drop-off ahead" in text for text in speak_texts)
    assert any("Possible stairs/drop-off ahead. Confirm stop?" in text for text in confirm_texts)
    assert any(str(row.get("type", "")).lower() == "confirm" for row in actions)

    planner = payload.get("meta", {}).get("planner", {})
    assert planner.get("ruleApplied") is True
    assert planner.get("ruleHazardHint") == "stairs_or_dropoff"
