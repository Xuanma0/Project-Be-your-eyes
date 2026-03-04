from __future__ import annotations

import io

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockDetBackend
from main import app, gateway


def test_overlay_event_contract_det_roundtrip() -> None:
    original_enable_det = gateway.config.inference_enable_det
    original_det_backend = gateway.det_backend
    object.__setattr__(gateway.config, "inference_enable_det", True)
    gateway.det_backend = MockDetBackend(model_id="mock-det-v5")
    gateway.drain_inference_events()
    gateway.asset_cache.reset()
    try:
        with TestClient(app) as client:
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            response = client.post("/api/frame", files=files)
            assert response.status_code == 200

            rows = gateway.drain_inference_events()
            overlay_row = next((row for row in rows if row.get("name") == "vis.overlay.v1"), None)
            assert isinstance(overlay_row, dict)
            payload = overlay_row.get("payload")
            assert isinstance(payload, dict)
            assert payload.get("schemaVersion") == "byes.vis.overlay.v1"
            assert payload.get("kind") == "det"
            asset_id = str(payload.get("assetId") or "").strip()
            assert asset_id
            assert int(payload.get("w", 0)) > 0
            assert int(payload.get("h", 0)) > 0

            asset_resp = client.get(f"/api/assets/{asset_id}")
            assert asset_resp.status_code == 200
            assert asset_resp.headers.get("content-type", "").startswith("image/png")
            assert asset_resp.content.startswith(b"\x89PNG")
    finally:
        object.__setattr__(gateway.config, "inference_enable_det", original_enable_det)
        gateway.det_backend = original_det_backend
        gateway.drain_inference_events()
