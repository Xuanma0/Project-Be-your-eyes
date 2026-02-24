from __future__ import annotations

from byes.inference.event_emitters import _normalize_seg_payload


def test_seg_mask_normalization_invalid_mask_dropped_with_warning() -> None:
    payload = {}
    rows = [
        {
            "label": "person",
            "score": 0.8,
            "bbox": [0, 0, 4, 4],
            "mask": {"format": "rle_v1", "size": [4, 4], "counts": [0, 2, 2]},
        }
    ]

    normalized = _normalize_seg_payload(payload, rows)
    segments = normalized.get("segments", [])
    assert isinstance(segments, list) and len(segments) == 1
    assert "mask" not in segments[0]
    assert int(normalized.get("warningsCount", 0)) >= 1


def test_seg_mask_normalization_valid_mask_kept() -> None:
    payload = {}
    rows = [
        {
            "label": "person",
            "score": 0.8,
            "bbox": [0, 0, 4, 4],
            "mask": {"format": "rle_v1", "size": [4, 4], "counts": [0, 2, 2, 2, 10]},
        }
    ]

    normalized = _normalize_seg_payload(payload, rows)
    segments = normalized.get("segments", [])
    assert isinstance(segments, list) and len(segments) == 1
    mask = segments[0].get("mask")
    assert isinstance(mask, dict)
    assert mask.get("format") == "rle_v1"
    assert mask.get("size") == [4, 4]
    assert mask.get("counts") == [0, 2, 2, 2, 10]
