from __future__ import annotations

import io

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockDepthBackend
from main import app, gateway


def test_assets_endpoint_returns_png_for_depth_overlay() -> None:
    original_enable_depth = gateway.config.inference_enable_depth
    original_depth_backend = gateway.depth_backend
    object.__setattr__(gateway.config, "inference_enable_depth", True)
    gateway.depth_backend = MockDepthBackend(model_id="mock-depth-v5")
    gateway.drain_inference_events()
    gateway.asset_cache.reset()
    try:
        with TestClient(app) as client:
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            response = client.post("/api/frame", files=files)
            assert response.status_code == 200

            rows = gateway.drain_inference_events()
            overlay_row = next((row for row in rows if row.get("name") == "depth.map.v1"), None)
            assert isinstance(overlay_row, dict)
            payload = overlay_row.get("payload")
            assert isinstance(payload, dict)
            asset_id = str(payload.get("assetId") or "").strip()
            assert asset_id

            asset_resp = client.get(f"/api/assets/{asset_id}")
            assert asset_resp.status_code == 200
            assert asset_resp.headers.get("content-type", "").startswith("image/png")
            assert asset_resp.content.startswith(b"\x89PNG")
    finally:
        object.__setattr__(gateway.config, "inference_enable_depth", original_enable_depth)
        gateway.depth_backend = original_depth_backend
        gateway.drain_inference_events()
