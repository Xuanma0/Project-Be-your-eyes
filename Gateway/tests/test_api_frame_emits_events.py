from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockOCRBackend, MockRiskBackend
from main import app, gateway


def test_api_frame_emits_inference_events_v1() -> None:
    original_enable_ocr = gateway.config.inference_enable_ocr
    original_enable_risk = gateway.config.inference_enable_risk
    original_emit_ws = gateway.config.inference_emit_ws_events_v1
    original_component = gateway.config.inference_event_component
    original_ocr_backend = gateway.ocr_backend
    original_risk_backend = gateway.risk_backend

    object.__setattr__(gateway.config, "inference_enable_ocr", True)
    object.__setattr__(gateway.config, "inference_enable_risk", True)
    object.__setattr__(gateway.config, "inference_emit_ws_events_v1", False)
    object.__setattr__(gateway.config, "inference_event_component", "gateway")
    gateway.ocr_backend = MockOCRBackend(text="EXIT")
    gateway.risk_backend = MockRiskBackend(hazards=[{"hazardKind": "stair_down", "severity": "warning"}])
    gateway.drain_inference_events()

    try:
        with TestClient(app) as client:
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            meta = json.dumps({"ttlMs": 5000, "sessionId": "session-a"})
            response = client.post("/api/frame", files=files, data={"meta": meta})
            assert response.status_code == 200
            seq = int(response.json().get("seq", 0))
            assert seq > 0

            rows = gateway.drain_inference_events()
            assert rows
            names = [str(item.get("name", "")) for item in rows]
            assert "ocr.scan_text" in names
            assert "risk.hazards" in names
            for item in rows:
                assert item.get("schemaVersion") == "byes.event.v1"
                if item.get("name") in {"ocr.scan_text", "risk.hazards"}:
                    assert item.get("frameSeq") == seq
    finally:
        object.__setattr__(gateway.config, "inference_enable_ocr", original_enable_ocr)
        object.__setattr__(gateway.config, "inference_enable_risk", original_enable_risk)
        object.__setattr__(gateway.config, "inference_emit_ws_events_v1", original_emit_ws)
        object.__setattr__(gateway.config, "inference_event_component", original_component)
        gateway.ocr_backend = original_ocr_backend
        gateway.risk_backend = original_risk_backend
        gateway.drain_inference_events()
