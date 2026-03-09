from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockDepthBackend, MockSegBackend
from main import app, gateway


def test_api_frame_emits_seg_and_depth_v1_events_with_asset_id() -> None:
    original_enable_seg = gateway.config.inference_enable_seg
    original_enable_depth = gateway.config.inference_enable_depth
    original_emit_ws = gateway.config.inference_emit_ws_events_v1
    original_seg_backend = gateway.seg_backend
    original_depth_backend = gateway.depth_backend

    try:
        with TestClient(app) as client:
            object.__setattr__(gateway.config, "inference_enable_seg", True)
            object.__setattr__(gateway.config, "inference_enable_depth", True)
            object.__setattr__(gateway.config, "inference_emit_ws_events_v1", False)
            gateway.seg_backend = MockSegBackend(
                segments=[
                    {
                        "label": "target",
                        "score": 0.95,
                        "bbox": [8.0, 8.0, 24.0, 24.0],
                        "mask": {"format": "rle_v1", "size": [4, 4], "counts": [4, 4, 4, 4]},
                    }
                ]
            )
            gateway.depth_backend = MockDepthBackend(grid_size=(8, 8))
            gateway.asset_cache.reset()
            gateway.drain_inference_events()

            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            meta = json.dumps(
                {
                    "ttlMs": 5000,
                    "runId": "seg-depth-v1-run",
                    "deviceId": "seg-depth-v1-device",
                    "targets": ["seg", "depth"],
                    "forceTargets": ["seg", "depth"],
                }
            )
            response = client.post("/api/frame", files=files, data={"meta": meta})
            assert response.status_code == 200
            seq = int(response.json().get("seq", 0))
            assert seq > 0

            rows = gateway.drain_inference_events()
            seg_rows = [row for row in rows if str(row.get("name", "")).strip() == "seg.mask.v1"]
            depth_rows = [row for row in rows if str(row.get("name", "")).strip() == "depth.map.v1"]
            assert seg_rows
            assert depth_rows

            seg_payload = seg_rows[-1].get("payload")
            depth_payload = depth_rows[-1].get("payload")
            assert isinstance(seg_payload, dict)
            assert isinstance(depth_payload, dict)
            assert seg_payload.get("schemaVersion") == "byes.seg.mask.v1"
            assert depth_payload.get("schemaVersion") == "byes.depth.map.v1"

            seg_asset_id = str(seg_payload.get("assetId", "")).strip()
            depth_asset_id = str(depth_payload.get("assetId", "")).strip()
            assert seg_asset_id
            assert depth_asset_id

            seg_asset_resp = client.get(f"/api/assets/{seg_asset_id}")
            depth_asset_resp = client.get(f"/api/assets/{depth_asset_id}")
            assert seg_asset_resp.status_code == 200
            assert depth_asset_resp.status_code == 200
            assert seg_asset_resp.headers.get("content-type", "").startswith("image/")
            assert depth_asset_resp.headers.get("content-type", "").startswith("image/")
    finally:
        object.__setattr__(gateway.config, "inference_enable_seg", original_enable_seg)
        object.__setattr__(gateway.config, "inference_enable_depth", original_enable_depth)
        object.__setattr__(gateway.config, "inference_emit_ws_events_v1", original_emit_ws)
        gateway.seg_backend = original_seg_backend
        gateway.depth_backend = original_depth_backend
        gateway.asset_cache.reset()
        gateway.drain_inference_events()
