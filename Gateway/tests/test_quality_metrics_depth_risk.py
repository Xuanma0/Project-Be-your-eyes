from __future__ import annotations

from byes.quality_metrics import compute_depth_risk_metrics


def test_compute_depth_risk_metrics_window_match() -> None:
    gt_map = {
        1: [{"hazardKind": "stair_down", "severity": "critical"}],
        5: [{"hazardKind": "obstacle", "severity": "warning"}],
    }
    pred_map = {
        2: [{"hazardKind": "stair_down"}],
        5: [{"hazardKind": "glass"}],
        9: [{"hazardKind": "obstacle"}],
    }

    metrics = compute_depth_risk_metrics(gt_map, pred_map, window_frames=2)

    assert metrics["matchWindowFrames"] == 2

    by_kind = metrics["byKind"]
    assert by_kind["stair_down"]["tp"] == 1
    assert by_kind["stair_down"]["fp"] == 0
    assert by_kind["stair_down"]["fn"] == 0

    assert by_kind["obstacle"]["tp"] == 0
    assert by_kind["obstacle"]["fp"] == 1
    assert by_kind["obstacle"]["fn"] == 1

    assert by_kind["glass"]["tp"] == 0
    assert by_kind["glass"]["fp"] == 1
    assert by_kind["glass"]["fn"] == 0

    overall = metrics["overall"]
    assert overall["tp"] == 1
    assert overall["fp"] == 2
    assert overall["fn"] == 1

    critical = metrics["critical"]
    assert critical["gtCriticalCount"] == 1
    assert critical["hitCriticalCount"] == 1
    assert critical["missCriticalCount"] == 0
