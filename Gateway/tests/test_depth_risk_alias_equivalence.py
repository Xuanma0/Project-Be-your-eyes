from __future__ import annotations

from byes.quality_metrics import compute_depth_risk_metrics


def test_depth_risk_alias_equivalence() -> None:
    gt_map = {
        10: [{"hazardKind": "dropoff", "severity": "critical"}],
    }
    pred_map = {
        11: [{"hazardKind": "stair_down_edge", "severity": "critical"}],
    }

    metrics = compute_depth_risk_metrics(gt_map, pred_map, window_frames=2)
    overall = metrics["overall"]
    assert overall["tp"] == 1
    assert overall["fp"] == 0
    assert overall["fn"] == 0
    assert metrics["byKind"]["dropoff"]["tp"] == 1
