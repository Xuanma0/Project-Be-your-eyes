from __future__ import annotations

from byes.risk_calibration import build_calibration_latency_metrics


def test_validate_risk_latency_from_events_marks_invalid_when_missing_or_zero() -> None:
    events = [
        {
            "category": "tool",
            "name": "risk.hazards",
            "phase": "result",
            "status": "ok",
        },
        {
            "category": "tool",
            "name": "risk.hazards",
            "phase": "result",
            "status": "ok",
            "latencyMs": 0,
        },
        {
            "category": "tool",
            "name": "risk.hazards",
            "phase": "result",
            "status": "ok",
            "latencyMs": None,
        },
    ]

    metrics = build_calibration_latency_metrics(events)
    stats = metrics.get("riskLatency", {})
    notes = metrics.get("notes", [])

    assert stats["valid"] is False
    assert metrics["riskLatencyP90"] is None
    assert stats["max"] is None
    assert "latency_invalid" in notes


def test_validate_risk_latency_from_events_uses_non_zero_values() -> None:
    events = [
        {
            "category": "tool",
            "name": "risk.hazards",
            "phase": "result",
            "status": "ok",
            "latencyMs": 100,
        },
        {
            "category": "tool",
            "name": "risk.hazards",
            "phase": "result",
            "status": "ok",
            "latencyMs": 300,
        },
    ]

    metrics = build_calibration_latency_metrics(events)
    stats = metrics.get("riskLatency", {})
    assert stats["valid"] is True
    assert stats["totalCount"] == 2
    assert stats["positiveCount"] == 2
    assert metrics["riskLatencyP90"] == 300
    assert stats["max"] == 300
