from __future__ import annotations

from byes.quality_metrics import extract_frame_e2e_summary_from_events_v1


def _frame_event(*, run_id: str, frame_seq: int, ts_ms: int, total_ms: int, parts: dict[str, int | None]) -> dict:
    return {
        "schemaVersion": "byes.event.v1",
        "tsMs": ts_ms,
        "runId": run_id,
        "frameSeq": frame_seq,
        "category": "frame",
        "name": "frame.e2e",
        "phase": "result",
        "status": "ok",
        "payload": {
            "schemaVersion": "frame.e2e.v1",
            "runId": run_id,
            "frameSeq": frame_seq,
            "t0Ms": ts_ms - total_ms,
            "t1Ms": ts_ms,
            "totalMs": total_ms,
            "partsMs": parts,
            "present": {
                "seg": parts.get("segMs") is not None,
                "risk": parts.get("riskMs") is not None,
                "plan": parts.get("planMs") is not None,
                "execute": parts.get("executeMs") is not None,
                "confirm": parts.get("confirmMs") is not None,
            },
        },
    }


def test_extract_frame_e2e_summary_dedupes_and_tracks_consistency() -> None:
    events = [
        _frame_event(
            run_id="run-a",
            frame_seq=1,
            ts_ms=1000,
            total_ms=40,
            parts={"segMs": 10, "riskMs": 10, "planMs": 10, "executeMs": None, "confirmMs": None},
        ),
        _frame_event(
            run_id="run-a",
            frame_seq=1,
            ts_ms=1010,
            total_ms=50,
            parts={"segMs": 20, "riskMs": 20, "planMs": 20, "executeMs": None, "confirmMs": None},
        ),
        _frame_event(
            run_id="run-a",
            frame_seq=2,
            ts_ms=1020,
            total_ms=30,
            parts={"segMs": 10, "riskMs": 10, "planMs": 5, "executeMs": None, "confirmMs": None},
        ),
    ]

    summary = extract_frame_e2e_summary_from_events_v1(events, frames_total_declared=2)
    assert bool(summary.get("present")) is True
    assert int(summary.get("events", 0) or 0) == 2
    assert int(summary.get("duplicatesDropped", 0) or 0) == 1
    assert int(summary.get("partsSumGtTotalCount", 0) or 0) == 1
    coverage = summary.get("coverage", {})
    assert int(coverage.get("framesWithE2E", 0) or 0) == 2
