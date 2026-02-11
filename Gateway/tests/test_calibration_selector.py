from __future__ import annotations

from byes.risk_calibration import expand_grid, select_best_candidates


def test_expand_grid_generates_product() -> None:
    rows = expand_grid({"a": [1, 2], "b": [10, 20]})
    assert len(rows) == 4
    assert {"a": 1.0, "b": 10.0} in rows
    assert {"a": 2.0, "b": 20.0} in rows


def test_select_best_candidates_prefers_zero_critical_fn_then_fp_quality_latency() -> None:
    results = [
        {"params": {"depthObsCrit": 0.45}, "critical_fn": 1, "fp_total": 0, "qualityScore": 95.0, "riskLatencyP90": 90},
        {"params": {"depthObsCrit": 0.55}, "critical_fn": 0, "fp_total": 2, "qualityScore": 98.0, "riskLatencyP90": 120},
        {"params": {"depthObsCrit": 0.65}, "critical_fn": 0, "fp_total": 2, "qualityScore": 99.0, "riskLatencyP90": 130},
        {"params": {"depthObsCrit": 0.75}, "critical_fn": 0, "fp_total": 1, "qualityScore": 90.0, "riskLatencyP90": 200},
    ]
    best, topk = select_best_candidates(results, must_zero_critical_fn=True, top_k=3)
    assert best is not None
    assert best.get("params", {}).get("depthObsCrit") == 0.75
    assert len(topk) == 3
    assert all(int(item.get("critical_fn", 1)) == 0 for item in topk)


def test_select_best_candidates_without_zero_fn_filter() -> None:
    results = [
        {"params": {"depthObsCrit": 0.45}, "critical_fn": 1, "fp_total": 0, "qualityScore": 90.0, "riskLatencyP90": 100},
        {"params": {"depthObsCrit": 0.55}, "critical_fn": 2, "fp_total": 1, "qualityScore": 99.0, "riskLatencyP90": 90},
    ]
    best, _topk = select_best_candidates(results, must_zero_critical_fn=False, top_k=2)
    assert best is not None
    assert best.get("params", {}).get("depthObsCrit") == 0.45
