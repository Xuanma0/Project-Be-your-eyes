from __future__ import annotations

from byes.event_normalizer import SCHEMA_VERSION, normalize_event


def test_normalize_legacy_event_to_v1() -> None:
    raw = {
        "receivedAtMs": 1700000000000,
        "event": {
            "type": "perception",
            "toolName": "real_ocr",
            "name": "scan_text_request",
            "frameSeq": 12,
            "latencyMs": 120,
            "payload": {"text": "EXIT"},
        },
    }
    event, warnings = normalize_event(raw)
    assert warnings == []
    assert event is not None
    assert event["schemaVersion"] == SCHEMA_VERSION
    assert event["name"] == "ocr.scan_text"
    assert event["phase"] == "start"
    assert event["frameSeq"] == 12
    assert event["payload"]["text"] == "EXIT"


def test_normalize_v1_passthrough() -> None:
    raw = {
        "schemaVersion": SCHEMA_VERSION,
        "tsMs": 1700000000000,
        "frameSeq": 3,
        "component": "gateway",
        "category": "safety",
        "name": "safety.confirm",
        "phase": "error",
        "status": "timeout",
        "latencyMs": None,
        "payload": {"reason": "timeout"},
    }
    event, warnings = normalize_event(raw)
    assert warnings == []
    assert event is not None
    assert event["name"] == "safety.confirm"
    assert event["status"] == "timeout"


def test_frame_seq_from_filename_and_ts_seconds_to_ms() -> None:
    raw = {
        "time": 1700000000,
        "event": {
            "type": "risk",
            "filename": "frame_42.jpg",
            "payload": {"hazards": [{"hazardKind": "stair_down"}]},
        },
    }
    event, _warnings = normalize_event(raw)
    assert event is not None
    assert event["frameSeq"] == 42
    assert event["tsMs"] == 1700000000000
    assert event["name"] in {"risk.hazards", "risk.depth"}
