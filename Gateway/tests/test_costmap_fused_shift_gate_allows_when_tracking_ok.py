from __future__ import annotations

import base64

from byes.mapping.costmap_fuser import CostmapFuser


def _raw_payload(values: list[int]) -> dict[str, object]:
    return {
        "schemaVersion": "byes.costmap.v1",
        "runId": "fixture-costmap-fused-gate-allow",
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
            "dynamicFilteredRate": 0.1,
            "sources": {"depth": True, "seg": True, "slam": True},
        },
    }


def test_costmap_fused_shift_gate_allows_when_tracking_ok() -> None:
    fuser = CostmapFuser()
    raw = _raw_payload([0, 0, 0, 0, 0, 200, 220, 0, 0, 210, 255, 0, 0, 0, 0, 0])

    fuser.update(
        run_id="fixture-costmap-fused-gate-allow",
        frame_seq=1,
        raw_costmap_payload=raw,
        slam_payload={"model": "pyslam-final", "trackingState": "tracking", "pose": {"t": [0.0, 0.0, 0.0]}},
        config={"shiftEnabled": True, "shiftGateEnabled": True, "minTrackingRate": 0.5, "maxLostStreak": 2},
    )
    out = fuser.update(
        run_id="fixture-costmap-fused-gate-allow",
        frame_seq=2,
        raw_costmap_payload=raw,
        slam_payload={"model": "pyslam-final", "trackingState": "tracking", "pose": {"t": [0.1, 0.0, 0.0]}},
        config={"shiftEnabled": True, "shiftGateEnabled": True, "minTrackingRate": 0.5, "maxLostStreak": 2},
    )

    fuse = out.get("fuse", {})
    fuse = fuse if isinstance(fuse, dict) else {}
    gate = fuse.get("gate", {})
    gate = gate if isinstance(gate, dict) else {}
    reasons = gate.get("reasons", [])
    reasons = reasons if isinstance(reasons, list) else []

    assert bool(gate.get("allowed")) is True
    assert bool(fuse.get("shiftUsed")) is True
    assert reasons == []

