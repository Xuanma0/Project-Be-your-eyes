from __future__ import annotations

import base64

from byes.mapping.costmap_fuser import CostmapFuser


def _raw_payload(values: list[int]) -> dict[str, object]:
    return {
        "schemaVersion": "byes.costmap.v1",
        "runId": "fixture-costmap-fused-builder",
        "frameSeq": 1,
        "frame": "local",
        "grid": {
            "format": "grid_u8_cost_v1",
            "size": [4, 4],
            "resolutionM": 0.1,
            "origin": {"x": 0.0, "y": 0.0},
            "dataB64": base64.b64encode(bytes(values)).decode("ascii"),
        },
        "stats": {
            "occupiedCells": sum(1 for item in values if int(item) > 0),
            "meanCost": float(sum(values)) / 16.0,
            "maxCost": max(values) if values else 0,
            "dynamicFilteredRate": 0.2,
            "sources": {"depth": True, "seg": True, "slam": True},
        },
    }


def test_costmap_fused_builder_shift_and_decay_min() -> None:
    fuser = CostmapFuser()
    raw1 = _raw_payload([0, 0, 0, 0, 0, 220, 240, 0, 0, 220, 255, 0, 0, 0, 0, 0])
    slam1 = {"pose": {"t": [0.0, 0.0, 0.0], "q": [0.0, 0.0, 0.0, 1.0]}}
    out1 = fuser.update(
        run_id="fixture-costmap-fused-builder",
        frame_seq=1,
        raw_costmap_payload=raw1,
        slam_payload=slam1,
        config={"alpha": 0.6, "decay": 0.95, "windowFrames": 10, "shiftEnabled": True, "occupiedThresh": 200},
    )

    stats1 = out1.get("stats", {})
    stats1 = stats1 if isinstance(stats1, dict) else {}
    stab1 = stats1.get("stability", {})
    stab1 = stab1 if isinstance(stab1, dict) else {}
    fuse1 = out1.get("fuse", {})
    fuse1 = fuse1 if isinstance(fuse1, dict) else {}
    assert bool(fuse1.get("shiftUsed")) is False
    assert stab1.get("iouPrev") is None
    assert float(stab1.get("flickerRatePrev", 0.0) or 0.0) == 0.0
    assert int(stats1.get("occupiedCells", 0) or 0) > 0

    raw2 = _raw_payload([0, 0, 0, 0, 0, 200, 220, 0, 0, 210, 230, 0, 0, 0, 0, 0])
    slam2 = {"pose": {"t": [0.1, 0.0, 0.0], "q": [0.0, 0.0, 0.0, 1.0]}}
    out2 = fuser.update(
        run_id="fixture-costmap-fused-builder",
        frame_seq=2,
        raw_costmap_payload=raw2,
        slam_payload=slam2,
        config={"alpha": 0.6, "decay": 0.95, "windowFrames": 10, "shiftEnabled": True, "occupiedThresh": 200},
    )

    fuse2 = out2.get("fuse", {})
    fuse2 = fuse2 if isinstance(fuse2, dict) else {}
    assert bool(fuse2.get("shiftUsed")) is True
    assert fuse2.get("shiftCells") == [1, 0]
    stats2 = out2.get("stats", {})
    stats2 = stats2 if isinstance(stats2, dict) else {}
    stab2 = stats2.get("stability", {})
    stab2 = stab2 if isinstance(stab2, dict) else {}
    assert "iouPrev" in stab2
    assert "flickerRatePrev" in stab2
    iou_prev = stab2.get("iouPrev")
    flicker_prev = stab2.get("flickerRatePrev")
    if iou_prev is not None:
        assert 0.0 <= float(iou_prev) <= 1.0
    if flicker_prev is not None:
        assert 0.0 <= float(flicker_prev) <= 1.0
