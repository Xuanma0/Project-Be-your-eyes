from __future__ import annotations

import base64

from byes.mapping.costmap import build_costmap_context_pack, find_latest_costmap_from_events


def _grid_b64(value: int) -> str:
    return base64.b64encode(bytes([value] * 16)).decode("ascii")


def test_costmap_context_prefers_fused_when_enabled() -> None:
    events = [
        {
            "schemaVersion": "byes.event.v1",
            "runId": "fixture-costmap-source",
            "frameSeq": 2,
            "name": "map.costmap",
            "phase": "result",
            "status": "ok",
            "payload": {
                "schemaVersion": "byes.costmap.v1",
                "runId": "fixture-costmap-source",
                "frameSeq": 2,
                "frame": "local",
                "grid": {"format": "grid_u8_cost_v1", "size": [4, 4], "resolutionM": 0.1, "dataB64": _grid_b64(150)},
                "stats": {
                    "occupiedCells": 16,
                    "meanCost": 150.0,
                    "maxCost": 150,
                    "dynamicFilteredRate": 0.1,
                    "sources": {"depth": True, "seg": True, "slam": True},
                },
            },
        },
        {
            "schemaVersion": "byes.event.v1",
            "runId": "fixture-costmap-source",
            "frameSeq": 2,
            "name": "map.costmap_fused",
            "phase": "result",
            "status": "ok",
            "payload": {
                "schemaVersion": "byes.costmap_fused.v1",
                "runId": "fixture-costmap-source",
                "frameSeq": 2,
                "frame": "local",
                "fuse": {"method": "ema_shift_v1", "alpha": 0.6, "decay": 0.95, "windowFrames": 10, "shiftUsed": True, "shiftCells": [1, 0]},
                "grid": {"format": "grid_u8_cost_v1", "size": [4, 4], "resolutionM": 0.1, "dataB64": _grid_b64(220)},
                "stats": {
                    "occupiedCells": 16,
                    "meanCost": 220.0,
                    "maxCost": 220,
                    "dynamicFilteredRate": 0.2,
                    "stability": {"iouPrev": 0.8, "flickerRatePrev": 0.1, "hotspotCount": 16},
                    "sources": {"depth": True, "seg": True, "slam": True},
                },
            },
        },
    ]

    selected = find_latest_costmap_from_events(
        events,
        run_id="fixture-costmap-source",
        frame_seq=2,
        source="auto",
    )
    assert isinstance(selected, dict)
    assert str(selected.get("schemaVersion", "")) == "byes.costmap_fused.v1"

    ctx = build_costmap_context_pack(
        costmap_payload=selected,
        budget={"maxChars": 128, "mode": "topk_hotspots"},
        source="fused",
    )
    text = ctx.get("text", {})
    text = text if isinstance(text, dict) else {}
    summary = str(text.get("summary", ""))
    assert "source=fused" in summary
