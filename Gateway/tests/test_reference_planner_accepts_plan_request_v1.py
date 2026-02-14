from __future__ import annotations

from services.planner_service.app import app as planner_app


def test_reference_planner_accepts_plan_request_v1() -> None:
    client = planner_app.test_client()
    response = client.post(
        "/plan",
        json={
            "schemaVersion": "byes.plan_request.v1",
            "runId": "fixture-plan-request-v1",
            "frameSeq": 1,
            "risk": {
                "riskLevel": "critical",
                "hazardsCount": 1,
                "backend": "http",
                "model": "heuristic-risk",
                "endpoint": "http://127.0.0.1:19120/risk"
            },
            "contexts": {
                "pov": {
                    "included": True,
                    "promptFragment": "POV decisions summary",
                    "chars": 22,
                    "tokenApprox": 6,
                    "truncation": {"dropped": 0}
                },
                "seg": {
                    "included": True,
                    "promptFragment": "[SEG] stairs ahead",
                    "chars": 18,
                    "tokenApprox": 5,
                    "truncation": {"segmentsDropped": 0, "charsDropped": 0}
                }
            },
            "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
            "meta": {"provider": "reference", "promptVersion": "v2", "createdAtMs": 1710000000000}
        },
    )
    assert response.status_code == 200, response.text
    payload = response.get_json()
    assert payload.get("schemaVersion") == "byes.action_plan.v1"
    planner = payload.get("meta", {}).get("planner", {})
    assert planner.get("model") in {"reference-planner-v1", "pov-ir-v1", "generic-llm-planner-v1"}
