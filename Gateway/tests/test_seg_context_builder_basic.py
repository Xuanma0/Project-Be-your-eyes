from __future__ import annotations

from byes.inference.seg_context import build_seg_context_from_events


def _seg_event(*, run_id: str, frame_seq: int, segments: list[dict]) -> dict:
    return {
        "schemaVersion": "byes.event.v1",
        "tsMs": 1713000000000 + frame_seq,
        "runId": run_id,
        "frameSeq": frame_seq,
        "component": "gateway",
        "category": "tool",
        "name": "seg.segment",
        "phase": "result",
        "status": "ok",
        "latencyMs": 20,
        "payload": {
            "segmentsCount": len(segments),
            "segments": segments,
            "backend": "mock",
            "model": "mock-seg",
            "endpoint": "",
        },
    }


def test_seg_context_builder_topk_and_label_grouped() -> None:
    events = [
        _seg_event(
            run_id="seg-ctx-fixture",
            frame_seq=1,
            segments=[
                {"label": "person", "score": 0.2, "bbox": [0, 0, 1, 1]},
            ],
        ),
        _seg_event(
            run_id="seg-ctx-fixture",
            frame_seq=2,
            segments=[
                {"label": "chair", "score": 0.9, "bbox": [2, 2, 4, 4]},
                {"label": "person", "score": 0.7, "bbox": [0, 0, 2, 2]},
            ],
        ),
    ]

    topk = build_seg_context_from_events(events, budget={"maxChars": 512, "maxSegments": 1, "mode": "topk_by_score"})
    assert topk["schemaVersion"] == "seg.context.v1"
    assert topk["runId"] == "seg-ctx-fixture"
    assert int(topk["stats"]["out"]["segments"]) == 1
    assert "chair" in str(topk["text"]["promptFragment"]).lower()

    grouped = build_seg_context_from_events(events, budget={"maxChars": 512, "maxSegments": 1, "mode": "label_grouped"})
    assert int(grouped["stats"]["out"]["segments"]) == 1
    assert int(grouped["stats"]["truncation"]["segmentsDropped"]) >= 1


def test_seg_context_builder_char_truncation() -> None:
    events = [
        _seg_event(
            run_id="seg-ctx-trunc",
            frame_seq=1,
            segments=[
                {"label": "person", "score": 0.99, "bbox": [0, 0, 10, 10]},
                {"label": "stairs", "score": 0.92, "bbox": [5, 5, 12, 12]},
            ],
        )
    ]
    payload = build_seg_context_from_events(events, budget={"maxChars": 24, "maxSegments": 4, "mode": "topk_by_score"})
    fragment = str(payload["text"]["promptFragment"])
    assert len(fragment) <= 24
    assert int(payload["stats"]["truncation"]["charsDropped"]) > 0
