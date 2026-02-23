from __future__ import annotations

import hashlib

from byes.mapping.costmap import build_local_costmap


def test_costmap_builder_deterministic_min() -> None:
    depth_payload = {
        "grid": {
            "format": "grid_u16_mm_v1",
            "size": [4, 4],
            "unit": "mm",
            "values": [
                600,
                700,
                800,
                900,
                600,
                700,
                800,
                900,
                700,
                800,
                900,
                1000,
                800,
                900,
                1000,
                1100,
            ],
        }
    }
    seg_payload = {
        "imageWidth": 4,
        "imageHeight": 4,
        "segments": [
            {
                "label": "person",
                "score": 0.95,
                "bbox": [0, 2, 2, 4],
                "mask": {"format": "rle_v1", "size": [4, 4], "counts": [8, 1, 7]},
            }
        ],
    }
    slam_payload = {"trackingState": "tracking", "pose": {"t": [0.0, 0.0, 0.0], "q": [0.0, 0.0, 0.0, 1.0]}}

    cfg = {"gridH": 4, "gridW": 4, "resolutionM": 0.1, "depthThreshM": 1.0, "dynamicLabels": ["person", "car"]}
    out1 = build_local_costmap(
        run_id="deterministic-costmap",
        frame_seq=1,
        depth_payload=depth_payload,
        seg_payload=seg_payload,
        slam_payload=slam_payload,
        config=cfg,
    )
    out2 = build_local_costmap(
        run_id="deterministic-costmap",
        frame_seq=1,
        depth_payload=depth_payload,
        seg_payload=seg_payload,
        slam_payload=slam_payload,
        config=cfg,
    )

    assert out1 == out2
    stats = out1.get("stats", {})
    assert int(stats.get("occupiedCells", 0) or 0) > 0
    assert float(stats.get("dynamicFilteredRate", 0.0) or 0.0) > 0.0
    data_b64 = str(out1.get("grid", {}).get("dataB64", ""))
    digest = hashlib.sha256(data_b64.encode("utf-8")).hexdigest()
    assert len(digest) == 64
