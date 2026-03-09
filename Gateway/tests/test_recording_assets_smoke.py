from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockDepthBackend, MockSegBackend
from main import app, gateway


def test_recording_includes_asset_files(tmp_path: Path) -> None:
    original_root = gateway.run_packages_root
    original_seg_flag = gateway.config.inference_enable_seg
    original_depth_flag = gateway.config.inference_enable_depth
    original_seg_backend = gateway.seg_backend
    original_depth_backend = gateway.depth_backend

    gateway.run_packages_root = tmp_path / "run_packages"
    gateway.recording = gateway.recording.__class__(
        run_packages_root=gateway.run_packages_root,
        asset_resolver=gateway.resolve_recording_asset,
    )
    gateway.asset_cache.reset()
    gateway.recording.reset()
    gateway.drain_inference_events()

    try:
        with TestClient(app) as client:
            object.__setattr__(gateway.config, "inference_enable_seg", True)
            object.__setattr__(gateway.config, "inference_enable_depth", True)
            gateway.seg_backend = MockSegBackend(
                segments=[
                    {
                        "label": "target",
                        "score": 0.9,
                        "bbox": [8.0, 8.0, 24.0, 24.0],
                        "mask": {"format": "rle_v1", "size": [4, 4], "counts": [4, 4, 4, 4]},
                    }
                ]
            )
            gateway.depth_backend = MockDepthBackend(grid_size=(8, 8))

            start_resp = client.post("/api/record/start", json={"deviceId": "asset-device"})
            assert start_resp.status_code == 200

            meta = json.dumps(
                {
                    "runId": "asset-run",
                    "deviceId": "asset-device",
                    "captureTsMs": 123,
                    "mode": "inspect",
                }
            )
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            frame_resp = client.post("/api/frame", files=files, data={"meta": meta})
            assert frame_resp.status_code == 200

            stop_resp = client.post("/api/record/stop", json={"deviceId": "asset-device"})
            assert stop_resp.status_code == 200
            root = Path(stop_resp.json()["recordingPath"])
            assert (root / "assets").exists()
            assets = list((root / "assets").glob("*"))
            assert assets, "expected recorded assets files"

            rows = gateway.drain_inference_events()
            names = [str(row.get("name", "")).strip() for row in rows]
            assert "seg.mask.v1" in names
            assert "depth.map.v1" in names
    finally:
        gateway.run_packages_root = original_root
        gateway.recording = gateway.recording.__class__(
            run_packages_root=gateway.run_packages_root,
            asset_resolver=gateway.resolve_recording_asset,
        )
        gateway.asset_cache.reset()
        gateway.recording.reset()
        object.__setattr__(gateway.config, "inference_enable_seg", original_seg_flag)
        object.__setattr__(gateway.config, "inference_enable_depth", original_depth_flag)
        gateway.seg_backend = original_seg_backend
        gateway.depth_backend = original_depth_backend
        gateway.drain_inference_events()
