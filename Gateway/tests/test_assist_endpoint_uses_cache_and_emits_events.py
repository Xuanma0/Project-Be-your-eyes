from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockDetBackend
from main import app, gateway


def test_assist_endpoint_uses_cached_frame_and_emits_events() -> None:
    original_enable_det = gateway.config.inference_enable_det
    original_emit_ws = gateway.config.inference_emit_ws_events_v1
    original_det_backend = gateway.det_backend

    object.__setattr__(gateway.config, "inference_enable_det", True)
    object.__setattr__(gateway.config, "inference_emit_ws_events_v1", False)
    gateway.det_backend = MockDetBackend()
    gateway.drain_inference_events()

    try:
        with TestClient(app) as client:
            meta = json.dumps(
                {
                    "runId": "assist-run",
                    "deviceId": "assist-device",
                    "captureTsMs": 1000,
                    "mode": "walk",
                }
            )
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            frame_resp = client.post("/api/frame", files=files, data={"meta": meta})
            assert frame_resp.status_code == 200

            # Clear events from the initial /api/frame; we only validate /api/assist output.
            gateway.drain_inference_events()

            assist_resp = client.post(
                "/api/assist",
                json={
                    "deviceId": "assist-device",
                    "action": "find",
                    "prompt": {"text": "door,exit sign"},
                    "maxAgeMs": 1500,
                },
            )
            assert assist_resp.status_code == 200
            payload = assist_resp.json()
            assert payload["ok"] is True
            assert payload["deviceId"] == "assist-device"
            assert "det" in payload["targets"]
            assert int(payload["cacheAgeMs"]) >= 0

            rows = gateway.drain_inference_events()
            names = [str(row.get("name", "")).strip() for row in rows]
            assert "assist.trigger" in names
            assert "det.objects" in names
    finally:
        object.__setattr__(gateway.config, "inference_enable_det", original_enable_det)
        object.__setattr__(gateway.config, "inference_emit_ws_events_v1", original_emit_ws)
        gateway.det_backend = original_det_backend
        gateway.drain_inference_events()


def test_assist_endpoint_returns_404_when_cache_miss() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/assist",
            json={
                "deviceId": "missing-device",
                "action": "ocr",
                "maxAgeMs": 200,
            },
        )
    assert response.status_code == 404
    assert response.json().get("detail") == "assist_cache_miss"
