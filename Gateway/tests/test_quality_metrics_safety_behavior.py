from __future__ import annotations

import json
from pathlib import Path

from byes.quality_metrics import extract_safety_behavior_from_ws_events


def test_extract_safety_behavior_metrics(tmp_path: Path) -> None:
    ws_path = tmp_path / "ws_events.jsonl"
    base_ms = 1_704_000_000_000
    rows = [
        {"receivedAtMs": base_ms + 1000, "event": {"type": "action_plan", "name": "confirm_request", "frameSeq": 10, "requestId": "r1"}},
        {"receivedAtMs": base_ms + 1200, "event": {"type": "event", "name": "confirm_done", "frameSeq": 10, "requestId": "r1"}},
        {"receivedAtMs": base_ms + 1300, "event": {"type": "action_plan", "name": "confirm_request", "frameSeq": 11, "requestId": "r2"}},
        {"receivedAtMs": base_ms + 1700, "event": {"type": "health", "summary": "confirm_timeout", "frameSeq": 11, "requestId": "r2"}},
        {"receivedAtMs": base_ms + 1800, "event": {"type": "action_plan", "summary": "double_check", "frameSeq": 12, "requestId": "r3"}},
        {"receivedAtMs": base_ms + 1900, "event": {"type": "health", "summary": "critical_latch_enter", "frameSeq": 10, "durationMs": 350}},
        {"receivedAtMs": base_ms + 2000, "event": {"type": "health", "summary": "preempt_window_enter", "frameSeq": 20}},
        {"receivedAtMs": base_ms + 2100, "event": {"type": "health", "summary": "local_fallback triggered"}},
    ]
    with ws_path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    metrics = extract_safety_behavior_from_ws_events(ws_path, critical_frame_seqs={11}, near_window_frames=2)

    confirm = metrics["confirm"]
    assert confirm["requests"] == 3
    assert confirm["responses"] == 1
    assert confirm["timeouts"] == 1
    assert confirm["missingResponseCount"] == 1
    assert confirm["framesWithConfirmIntent"] == 3
    assert isinstance(confirm["latencyMs"], dict)
    assert confirm["latencyMs"]["count"] == 1
    assert confirm["latencyMs"]["p50"] == 200

    latch = metrics["latch"]
    assert latch["count"] == 1
    assert latch["nearCriticalCount"] == 1
    assert latch["durationMs"]["p50"] == 350

    preempt = metrics["preempt"]
    assert preempt["count"] == 1
    assert preempt["nearCriticalCount"] == 0

    fallback = metrics["fallback"]
    assert fallback["localFallbackCount"] == 1
