from __future__ import annotations

import io
import json

import httpx
from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockOCRBackend, MockRiskBackend
from byes.inference.registry import get_ocr_backend, get_risk_backend
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
            assert "ocr.read" in names
            assert "risk.hazards" in names
            for item in rows:
                assert item.get("schemaVersion") == "byes.event.v1"
                if item.get("name") in {"ocr.read", "risk.hazards"}:
                    assert item.get("frameSeq") == seq
                    payload = item.get("payload")
                    assert isinstance(payload, dict)
                    if item.get("phase") != "start":
                        assert payload.get("backend") == "mock"
                        assert "latencyMs" not in payload
    finally:
        object.__setattr__(gateway.config, "inference_enable_ocr", original_enable_ocr)
        object.__setattr__(gateway.config, "inference_enable_risk", original_enable_risk)
        object.__setattr__(gateway.config, "inference_emit_ws_events_v1", original_emit_ws)
        object.__setattr__(gateway.config, "inference_event_component", original_component)
        gateway.ocr_backend = original_ocr_backend
        gateway.risk_backend = original_risk_backend
        gateway.drain_inference_events()


def test_api_frame_emits_http_backend_metadata(monkeypatch) -> None:
    original_enable_ocr = gateway.config.inference_enable_ocr
    original_enable_risk = gateway.config.inference_enable_risk
    original_emit_ws = gateway.config.inference_emit_ws_events_v1
    original_component = gateway.config.inference_event_component
    original_ocr_backend = gateway.ocr_backend
    original_risk_backend = gateway.risk_backend

    async def _fake_post(self, url: str, json: dict | None = None, **kwargs):  # noqa: ANN001
        del self, kwargs

        class _Response:
            def __init__(self, status_code: int, payload: dict[str, object]) -> None:
                self.status_code = status_code
                self._payload = payload

            def json(self) -> dict[str, object]:
                return self._payload

        if str(url).endswith("/ocr"):
            return _Response(200, {"text": "EXIT", "model": "paddleocr-v4"})
        if str(url).endswith("/risk"):
            return _Response(200, {"hazards": [{"hazardKind": "stair_down", "severity": "warning"}], "model": "depth-v2"})
        return _Response(404, {"error": "not_found"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setenv("BYES_OCR_BACKEND", "http")
    monkeypatch.setenv("BYES_OCR_HTTP_URL", "http://127.0.0.1:9001/ocr")
    monkeypatch.setenv("BYES_OCR_MODEL_ID", "paddleocr-v4")
    monkeypatch.setenv("BYES_RISK_BACKEND", "http")
    monkeypatch.setenv("BYES_RISK_HTTP_URL", "http://127.0.0.1:9002/risk")
    monkeypatch.setenv("BYES_RISK_MODEL_ID", "depth-anything-v2-small")

    object.__setattr__(gateway.config, "inference_enable_ocr", True)
    object.__setattr__(gateway.config, "inference_enable_risk", True)
    object.__setattr__(gateway.config, "inference_emit_ws_events_v1", False)
    object.__setattr__(gateway.config, "inference_event_component", "gateway")
    gateway.ocr_backend = get_ocr_backend(gateway.config)
    gateway.risk_backend = get_risk_backend(gateway.config)
    gateway.drain_inference_events()

    try:
        with TestClient(app) as client:
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            meta = json.dumps({"ttlMs": 5000, "sessionId": "session-http"})
            response = client.post("/api/frame", files=files, data={"meta": meta})
            assert response.status_code == 200

            rows = gateway.drain_inference_events()
            assert rows
            ocr_result = next(item for item in rows if item.get("name") == "ocr.read" and item.get("phase") == "result")
            risk_result = next(item for item in rows if item.get("name") == "risk.hazards")
            ocr_payload = ocr_result.get("payload")
            risk_payload = risk_result.get("payload")
            assert isinstance(ocr_payload, dict)
            assert isinstance(risk_payload, dict)
            assert ocr_payload.get("backend") == "http"
            assert risk_payload.get("backend") == "http"
            assert ocr_payload.get("model") == "paddleocr-v4"
            assert risk_payload.get("model") == "depth-v2"
            assert ocr_payload.get("endpoint")
            assert risk_payload.get("endpoint")
            assert "latencyMs" not in ocr_payload
            assert "latencyMs" not in risk_payload
    finally:
        object.__setattr__(gateway.config, "inference_enable_ocr", original_enable_ocr)
        object.__setattr__(gateway.config, "inference_enable_risk", original_enable_risk)
        object.__setattr__(gateway.config, "inference_emit_ws_events_v1", original_emit_ws)
        object.__setattr__(gateway.config, "inference_event_component", original_component)
        gateway.ocr_backend = original_ocr_backend
        gateway.risk_backend = original_risk_backend
        gateway.drain_inference_events()
