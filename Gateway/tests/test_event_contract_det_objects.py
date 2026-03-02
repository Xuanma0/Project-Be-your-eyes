from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockDetBackend
from main import app, gateway


def test_api_frame_emits_det_objects_event() -> None:
    original_enable_det = gateway.config.inference_enable_det
    original_emit_ws = gateway.config.inference_emit_ws_events_v1
    original_component = gateway.config.inference_event_component
    original_det_backend = gateway.det_backend

    object.__setattr__(gateway.config, "inference_enable_det", True)
    object.__setattr__(gateway.config, "inference_emit_ws_events_v1", False)
    object.__setattr__(gateway.config, "inference_event_component", "gateway")
    gateway.det_backend = MockDetBackend()
    gateway.drain_inference_events()

    try:
        with TestClient(app) as client:
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            meta = json.dumps({"ttlMs": 5000, "sessionId": "session-det"})
            response = client.post("/api/frame", files=files, data={"meta": meta})
            assert response.status_code == 200
            seq = int(response.json().get("seq", 0))
            assert seq > 0

            rows = gateway.drain_inference_events()
            det_rows = [row for row in rows if str(row.get("name", "")).strip() == "det.objects"]
            assert det_rows
            det = det_rows[-1]
            assert det.get("schemaVersion") == "byes.event.v1"
            assert int(det.get("frameSeq", 0) or 0) == seq
            payload = det.get("payload")
            assert isinstance(payload, dict)
            assert payload.get("schemaVersion") == "byes.det.v1"
            assert isinstance(payload.get("objects"), list)
            assert int(payload.get("objectsCount", 0) or 0) >= 1
    finally:
        object.__setattr__(gateway.config, "inference_enable_det", original_enable_det)
        object.__setattr__(gateway.config, "inference_emit_ws_events_v1", original_emit_ws)
        object.__setattr__(gateway.config, "inference_event_component", original_component)
        gateway.det_backend = original_det_backend
        gateway.drain_inference_events()


def test_api_frame_force_targets_runs_det_when_profile_would_skip() -> None:
    original_enable_det = gateway.config.inference_enable_det
    original_emit_ws = gateway.config.inference_emit_ws_events_v1
    original_det_backend = gateway.det_backend

    object.__setattr__(gateway.config, "inference_enable_det", True)
    object.__setattr__(gateway.config, "inference_emit_ws_events_v1", False)
    gateway.det_backend = MockDetBackend()
    gateway.drain_inference_events()

    try:
        with TestClient(app) as client:
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            meta = json.dumps({"ttlMs": 5000, "sessionId": "session-det-targets", "targets": ["det"]})
            response = client.post("/api/frame", files=files, data={"meta": meta})
            assert response.status_code == 200
            rows = gateway.drain_inference_events()
            names = [str(item.get("name", "")).strip() for item in rows]
            assert "det.objects" in names
    finally:
        object.__setattr__(gateway.config, "inference_enable_det", original_enable_det)
        object.__setattr__(gateway.config, "inference_emit_ws_events_v1", original_emit_ws)
        gateway.det_backend = original_det_backend
        gateway.drain_inference_events()
