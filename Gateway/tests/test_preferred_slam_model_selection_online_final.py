from __future__ import annotations

import base64

from byes.mapping.costmap_fuser import CostmapFuser


def _raw_payload() -> dict[str, object]:
    values = [0, 0, 0, 0, 0, 180, 200, 0, 0, 200, 255, 0, 0, 0, 0, 0]
    return {
        "schemaVersion": "byes.costmap.v1",
        "runId": "fixture-costmap-preferred-model",
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
            "occupiedCells": 4,
            "meanCost": 52.0,
            "maxCost": 255,
            "dynamicFilteredRate": 0.0,
            "sources": {"depth": True, "seg": False, "slam": True},
        },
    }


def _run_with_model(preferred: str, model_name: str) -> str | None:
    fuser = CostmapFuser()
    raw = _raw_payload()
    fuser.update(
        run_id="fixture-costmap-preferred-model",
        frame_seq=1,
        raw_costmap_payload=raw,
        slam_payload={"model": model_name, "trackingState": "tracking", "pose": {"t": [0.0, 0.0, 0.0]}},
        config={"shiftEnabled": True, "shiftGateEnabled": True, "slamTrajPreferred": preferred},
    )
    out = fuser.update(
        run_id="fixture-costmap-preferred-model",
        frame_seq=2,
        raw_costmap_payload=raw,
        slam_payload={"model": model_name, "trackingState": "tracking", "pose": {"t": [0.1, 0.0, 0.0]}},
        config={"shiftEnabled": True, "shiftGateEnabled": True, "slamTrajPreferred": preferred},
    )
    fuse = out.get("fuse", {})
    fuse = fuse if isinstance(fuse, dict) else {}
    gate = fuse.get("gate", {})
    gate = gate if isinstance(gate, dict) else {}
    slam_model = gate.get("slamModel")
    return str(slam_model) if slam_model is not None else None


def test_preferred_slam_model_selection_online_final() -> None:
    selected_online = _run_with_model(preferred="online", model_name="pyslam-online")
    selected_final = _run_with_model(preferred="final", model_name="pyslam-final")
    assert selected_online == "pyslam-online"
    assert selected_final == "pyslam-final"

