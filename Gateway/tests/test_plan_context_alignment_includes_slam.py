from __future__ import annotations

from byes.plan_context_alignment import compute_plan_context_alignment


def test_plan_context_alignment_includes_slam_hit() -> None:
    plan_request = {
        "contexts": {
            "pov": {"included": False, "promptFragment": None, "chars": 0, "truncation": {"dropped": 0}},
            "seg": {
                "included": True,
                "promptFragment": "[SEG] stairs(0.95)",
                "chars": 18,
                "truncation": {"segmentsDropped": 0, "charsDropped": 0},
            },
            "slam": {
                "present": True,
                "chars": 78,
                "promptFragment": "[SLAM] state=tracking rate=0.95 lostStreak=0 alignP90=12ms",
            },
        }
    }
    plan = {
        "intent": "Navigation update",
        "actions": [
            {"type": "speak", "payload": {"text": "Tracking is stable. Continue forward carefully."}},
            {"type": "confirm", "payload": {"text": "Confirm tracking guidance?"}},
        ],
        "meta": {"contextUsedDetail": {"seg": True, "pov": False, "slam": True}},
    }

    alignment = compute_plan_context_alignment(plan_request, plan)
    slam = alignment.get("slam", {})
    slam = slam if isinstance(slam, dict) else {}
    assert bool(slam.get("present")) is True
    assert bool(slam.get("hit")) is True
    assert float(slam.get("coverage", 0.0) or 0.0) == 1.0
    detail = alignment.get("contextUsedDetail", {})
    detail = detail if isinstance(detail, dict) else {}
    assert bool(detail.get("slam")) is True
