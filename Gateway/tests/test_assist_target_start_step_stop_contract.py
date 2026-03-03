from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockDetBackend, MockSegBackend
from main import app, gateway


def test_assist_target_start_step_stop_contract() -> None:
    original_enable_det = gateway.config.inference_enable_det
    original_enable_seg = gateway.config.inference_enable_seg
    original_emit_ws = gateway.config.inference_emit_ws_events_v1
    original_det_backend = gateway.det_backend
    original_seg_backend = gateway.seg_backend

    object.__setattr__(gateway.config, "inference_enable_det", True)
    object.__setattr__(gateway.config, "inference_enable_seg", False)
    object.__setattr__(gateway.config, "inference_emit_ws_events_v1", False)
    gateway.det_backend = MockDetBackend()
    gateway.seg_backend = MockSegBackend()
    gateway.drain_inference_events()
    gateway.target_tracking.reset()

    try:
        with TestClient(app) as client:
            meta = json.dumps(
                {
                    "runId": "target-run",
                    "deviceId": "target-device",
                    "captureTsMs": 1111,
                    "mode": "inspect",
                }
            )
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            frame_resp = client.post("/api/frame", files=files, data={"meta": meta})
            assert frame_resp.status_code == 200
            gateway.drain_inference_events()

            start_resp = client.post(
                "/api/assist",
                json={
                    "deviceId": "target-device",
                    "action": "target_start",
                    "prompt": "door",
                    "roi": {"x": 0.2, "y": 0.2, "w": 0.4, "h": 0.4},
                    "tracker": "botsort",
                    "seg": {"enabled": False},
                },
            )
            assert start_resp.status_code == 200
            start_payload = start_resp.json()
            assert start_payload["ok"] is True
            assert start_payload["action"] == "target_start"
            assert str(start_payload.get("sessionId", "")).strip()

            start_rows = gateway.drain_inference_events()
            start_names = [str(row.get("name", "")).strip() for row in start_rows]
            assert "assist.trigger" in start_names
            assert "det.objects" in start_names
            assert "target.session" in start_names
            assert "target.update" in start_names

            session_id = str(start_payload.get("sessionId", "")).strip()
            step_resp = client.post(
                "/api/assist",
                json={
                    "deviceId": "target-device",
                    "action": "target_step",
                    "sessionId": session_id,
                },
            )
            assert step_resp.status_code == 200
            step_payload = step_resp.json()
            assert step_payload["ok"] is True
            assert step_payload.get("sessionId") == session_id

            step_rows = gateway.drain_inference_events()
            step_names = [str(row.get("name", "")).strip() for row in step_rows]
            assert "target.update" in step_names

            stop_resp = client.post(
                "/api/assist",
                json={
                    "deviceId": "target-device",
                    "action": "target_stop",
                    "sessionId": session_id,
                },
            )
            assert stop_resp.status_code == 200
            stop_payload = stop_resp.json()
            assert stop_payload["ok"] is True
            assert stop_payload["status"] == "closed"

            stop_rows = gateway.drain_inference_events()
            stop_session_rows = [
                row
                for row in stop_rows
                if str(row.get("name", "")).strip() == "target.session"
            ]
            assert stop_session_rows
            latest_payload = stop_session_rows[-1].get("payload")
            latest_payload = latest_payload if isinstance(latest_payload, dict) else {}
            assert str(latest_payload.get("status", "")).strip() == "closed"
    finally:
        object.__setattr__(gateway.config, "inference_enable_det", original_enable_det)
        object.__setattr__(gateway.config, "inference_enable_seg", original_enable_seg)
        object.__setattr__(gateway.config, "inference_emit_ws_events_v1", original_emit_ws)
        gateway.det_backend = original_det_backend
        gateway.seg_backend = original_seg_backend
        gateway.target_tracking.reset()
        gateway.drain_inference_events()
