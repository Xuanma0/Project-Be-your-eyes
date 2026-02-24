from __future__ import annotations

from services.planner_service.app import app as planner_app


def test_planner_service_accepts_plan_request_with_slam_context() -> None:
    client = planner_app.test_client()
    response = client.post(
        "/plan",
        json={
            "schemaVersion": "byes.plan_request.v1",
            "runId": "fixture-plan-request-slam-context-v1",
            "frameSeq": 2,
            "risk": {
                "riskLevel": "high",
                "hazardsCount": 1,
                "backend": "http",
                "model": "heuristic-risk",
                "endpoint": "http://127.0.0.1:19120/risk",
            },
            "contexts": {
                "pov": {
                    "included": True,
                    "promptFragment": "POV context fragment",
                    "chars": 20,
                    "tokenApprox": 5,
                    "truncation": {"dropped": 0},
                },
                "seg": {
                    "included": True,
                    "promptFragment": "[SEG] stairs(0.92) person(0.83)",
                    "chars": 31,
                    "tokenApprox": 8,
                    "truncation": {"segmentsDropped": 0, "charsDropped": 0},
                },
                "slam": {
                    "present": True,
                    "chars": 92,
                    "promptFragment": "[SLAM] state=tracking rate=0.95 lostStreak=0 alignP90=12ms speedP90=1.2m/s",
                },
            },
            "constraints": {"allowConfirm": True, "allowHaptic": False, "maxActions": 3},
            "meta": {
                "provider": "reference",
                "promptVersion": "v3",
                "createdAtMs": 1710000000000,
                "slamIncluded": True,
                "slamChars": 92,
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.get_json()
    assert payload.get("schemaVersion") == "byes.action_plan.v1"
    meta = payload.get("meta", {})
    meta = meta if isinstance(meta, dict) else {}
    planner = meta.get("planner", {})
    planner = planner if isinstance(planner, dict) else {}
    assert str(planner.get("promptVersion", "")).strip().lower() == "v3"
    detail = meta.get("contextUsedDetail")
    if not isinstance(detail, dict):
        detail = planner.get("contextUsedDetail")
    detail = detail if isinstance(detail, dict) else {}
    assert "slam" in detail
    assert isinstance(detail.get("slam"), bool)
