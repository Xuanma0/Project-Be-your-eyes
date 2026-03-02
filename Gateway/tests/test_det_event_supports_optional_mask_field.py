from __future__ import annotations

from services.inference_service.app import _normalize_det_objects


def test_normalize_det_objects_keeps_optional_mask_payload() -> None:
    rows, warnings_count = _normalize_det_objects(
        [
            {
                "label": "door",
                "conf": 0.91,
                "box_xyxy": [10, 20, 120, 200],
                "mask": {
                    "format": "polygon_v1",
                    "points": [[10, 20], [120, 20], [120, 200], [10, 200]],
                },
            },
            {
                "label": "person",
                "conf": 0.87,
                "box_xyxy": [40, 35, 160, 300],
            },
        ]
    )

    assert warnings_count == 0
    assert len(rows) == 2
    assert rows[0]["label"] == "door"
    assert isinstance(rows[0].get("mask"), dict)
    assert rows[0]["mask"]["format"] == "polygon_v1"
    assert "mask" not in rows[1]
