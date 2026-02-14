from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockSegBackend
from main import app, gateway


def test_api_frame_emits_seg_event_v1() -> None:
    original_enable_ocr = gateway.config.inference_enable_ocr
    original_enable_risk = gateway.config.inference_enable_risk
    original_enable_seg = gateway.config.inference_enable_seg
    original_seg_backend = gateway.seg_backend

    object.__setattr__(gateway.config, "inference_enable_ocr", False)
    object.__setattr__(gateway.config, "inference_enable_risk", False)
    object.__setattr__(gateway.config, "inference_enable_seg", True)
    gateway.seg_backend = MockSegBackend(
        segments=[{"label": "floor", "score": 0.9, "bbox": [0, 0, 10, 10]}],
        model_id="mock-seg-v1",
    )
    gateway.drain_inference_events()

    try:
        with TestClient(app) as client:
            gateway.seg_backend = MockSegBackend(
                segments=[{"label": "floor", "score": 0.9, "bbox": [0, 0, 10, 10]}],
                model_id="mock-seg-v1",
            )
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            meta = json.dumps({"ttlMs": 5000, "sessionId": "session-seg"})
            response = client.post("/api/frame", files=files, data={"meta": meta})
            assert response.status_code == 200

            rows = gateway.drain_inference_events()
            seg_row = next((row for row in rows if str(row.get("name", "")) == "seg.segment"), None)
            assert seg_row is not None
            assert seg_row.get("schemaVersion") == "byes.event.v1"
            assert seg_row.get("category") == "tool"
            assert seg_row.get("phase") == "result"
            payload = seg_row.get("payload", {})
            assert isinstance(payload, dict)
            assert int(payload.get("segmentsCount", -1)) == 1
            assert payload.get("backend") == "mock"
            assert payload.get("model") == "mock-seg-v1"
            assert "endpoint" in payload
    finally:
        object.__setattr__(gateway.config, "inference_enable_ocr", original_enable_ocr)
        object.__setattr__(gateway.config, "inference_enable_risk", original_enable_risk)
        object.__setattr__(gateway.config, "inference_enable_seg", original_enable_seg)
        gateway.seg_backend = original_seg_backend
        gateway.drain_inference_events()
