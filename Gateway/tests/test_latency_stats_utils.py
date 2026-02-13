from __future__ import annotations

from pathlib import Path

from byes.latency_stats import extract_risk_hazard_latencies, iter_jsonl, summarize_latency


def test_summarize_latency_percentiles() -> None:
    stats = summarize_latency([50, 10, 40, 30, 20], sample_size=3)
    assert stats["count"] == 5
    assert stats["p50"] == 30
    assert stats["p90"] == 50
    assert stats["p99"] == 50
    assert stats["max"] == 50
    assert stats["valuesSample"] == [10, 20, 30]


def test_extract_risk_hazard_latencies_from_events(tmp_path: Path) -> None:
    events_path = tmp_path / "events_v1.jsonl"
    events_path.write_text(
        "\n".join(
            [
                '{"schemaVersion":"byes.event.v1","category":"tool","name":"risk.hazards","phase":"result","status":"ok","latencyMs":120}',
                '{"schemaVersion":"byes.event.v1","category":"tool","name":"risk.hazards","phase":"start","status":"ok","latencyMs":30}',
                '{"schemaVersion":"byes.event.v1","category":"tool","name":"ocr.scan_text","phase":"result","status":"ok","latencyMs":90}',
                '{"event":{"schemaVersion":"byes.event.v1","category":"tool","name":"risk.hazards","phase":"result","status":"ok","latencyMs":"80"}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = iter_jsonl(events_path)
    latencies = extract_risk_hazard_latencies(rows)
    assert latencies == [120, 80]
    stats = summarize_latency(latencies)
    assert stats["p50"] == 80
    assert stats["p90"] == 120
    assert stats["max"] == 120
