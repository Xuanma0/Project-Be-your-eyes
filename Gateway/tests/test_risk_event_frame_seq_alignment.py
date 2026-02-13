from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockRiskBackend
from main import app, gateway


def test_risk_event_uses_client_frame_seq_for_alignment() -> None:
    original_enable_ocr = gateway.config.inference_enable_ocr
    original_enable_risk = gateway.config.inference_enable_risk
    original_emit_ws = gateway.config.inference_emit_ws_events_v1
    original_risk_backend = gateway.risk_backend

    object.__setattr__(gateway.config, "inference_enable_ocr", False)
    object.__setattr__(gateway.config, "inference_enable_risk", True)
    object.__setattr__(gateway.config, "inference_emit_ws_events_v1", False)
    gateway.risk_backend = MockRiskBackend(hazards=[{"hazardKind": "dropoff", "severity": "critical"}])
    gateway.drain_inference_events()

    try:
        with TestClient(app) as client:
            for seq in (1, 2):
                files = {"image": (f"frame_{seq}.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
                meta = json.dumps({"ttlMs": 5000, "frameSeq": seq, "sessionId": "seq-align"})
                response = client.post("/api/frame", files=files, data={"meta": meta})
                assert response.status_code == 200

            rows = gateway.drain_inference_events()
            risk_rows = [row for row in rows if row.get("name") == "risk.hazards"]
            assert len(risk_rows) >= 2
            frame_seqs = [int(row.get("frameSeq", 0)) for row in risk_rows[:2]]
            assert frame_seqs == [1, 2]
    finally:
        object.__setattr__(gateway.config, "inference_enable_ocr", original_enable_ocr)
        object.__setattr__(gateway.config, "inference_enable_risk", original_enable_risk)
        object.__setattr__(gateway.config, "inference_emit_ws_events_v1", original_emit_ws)
        gateway.risk_backend = original_risk_backend
        gateway.drain_inference_events()
