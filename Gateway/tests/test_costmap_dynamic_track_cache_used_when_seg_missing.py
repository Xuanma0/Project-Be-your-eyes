from __future__ import annotations

from byes.mapping.costmap import build_local_costmap
from byes.mapping.dynamic_mask_cache import DynamicMaskCache


def _depth_payload() -> dict[str, object]:
    return {
        "schemaVersion": "byes.depth.v1",
        "grid": {
            "format": "grid_u16_mm_v1",
            "size": [4, 4],
            "unit": "mm",
            "values": [700, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700],
        },
    }


def test_costmap_dynamic_track_cache_used_when_seg_missing() -> None:
    cache = DynamicMaskCache()
    cfg = {
        "gridH": 4,
        "gridW": 4,
        "resolutionM": 0.1,
        "depthThreshM": 1.0,
        "dynamicLabels": ["person", "car"],
        "enableDynamicTrack": True,
        "dynamicTrackTtlFrames": 5,
    }
    seg_with_track = {
        "schemaVersion": "byes.seg.v1",
        "imageWidth": 4,
        "imageHeight": 4,
        "segments": [
            {
                "label": "person",
                "trackId": "trk-1",
                "bbox": [0, 0, 2, 2],
                "mask": {"format": "rle_v1", "size": [4, 4], "counts": [0, 1, 3, 1, 11]},
            }
        ],
    }
    first = build_local_costmap(
        run_id="dyn-track-test",
        frame_seq=1,
        depth_payload=_depth_payload(),
        seg_payload=seg_with_track,
        slam_payload=None,
        config=cfg,
        dynamic_mask_cache=cache,
    )
    first_stats = first.get("stats", {})
    first_stats = first_stats if isinstance(first_stats, dict) else {}
    assert bool(first_stats.get("dynamicTemporalUsed")) is True
    assert bool(first_stats.get("dynamicMaskUsed")) is False
    assert int(first_stats.get("dynamicTracksUsed", 0) or 0) >= 1

    second = build_local_costmap(
        run_id="dyn-track-test",
        frame_seq=2,
        depth_payload=_depth_payload(),
        seg_payload={"schemaVersion": "byes.seg.v1", "segments": []},
        slam_payload=None,
        config=cfg,
        dynamic_mask_cache=cache,
    )
    second_stats = second.get("stats", {})
    second_stats = second_stats if isinstance(second_stats, dict) else {}
    assert bool(second_stats.get("dynamicTemporalUsed")) is True
    assert bool(second_stats.get("dynamicMaskUsed")) is True
    assert int(second_stats.get("dynamicTracksUsed", 0) or 0) >= 1
