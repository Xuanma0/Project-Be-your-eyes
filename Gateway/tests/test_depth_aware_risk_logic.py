from __future__ import annotations

import base64
import io

from fastapi.testclient import TestClient
from PIL import Image

from services.inference_service import app as inference_app
from services.inference_service.providers.depth_synth import SynthDepthProvider
from services.inference_service.providers.heuristic_risk import HeuristicRiskProvider


def _encode_image_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _blank_image() -> Image.Image:
    return Image.new("RGB", (320, 180), (160, 160, 160))


def _reset_service_globals() -> None:
    inference_app._OCR_PROVIDER = None  # type: ignore[attr-defined]
    inference_app._RISK_PROVIDER = None  # type: ignore[attr-defined]
    inference_app._DEPTH_PROVIDER = None  # type: ignore[attr-defined]


def test_depth_aware_risk_with_synth_provider(monkeypatch) -> None:
    monkeypatch.setenv("BYES_RISK_DEPTH_ENABLE", "1")
    monkeypatch.setenv("BYES_RISK_DEPTH_OBS_WARN", "1.0")
    monkeypatch.setenv("BYES_RISK_DEPTH_OBS_CRIT", "0.6")
    monkeypatch.setenv("BYES_RISK_DEPTH_DROPOFF_DELTA", "0.8")

    provider = HeuristicRiskProvider(depth_provider=SynthDepthProvider())
    frame2 = provider.infer(_blank_image(), frame_seq=2)
    hazards2 = frame2.get("hazards", [])
    assert isinstance(hazards2, list) and hazards2
    assert hazards2[0].get("hazardKind") == "dropoff"
    assert hazards2[0].get("severity") == "critical"

    frame3 = provider.infer(_blank_image(), frame_seq=3)
    hazards3 = frame3.get("hazards", [])
    assert isinstance(hazards3, list) and hazards3
    assert hazards3[0].get("hazardKind") == "obstacle_close"
    assert hazards3[0].get("severity") in {"warning", "critical"}


def test_risk_debug_payload_toggle(monkeypatch) -> None:
    monkeypatch.setenv("BYES_SERVICE_RISK_PROVIDER", "heuristic")
    monkeypatch.setenv("BYES_SERVICE_DEPTH_PROVIDER", "synth")
    monkeypatch.setenv("BYES_SERVICE_OCR_PROVIDER", "reference")
    monkeypatch.setenv("BYES_RISK_DEPTH_ENABLE", "1")
    monkeypatch.setenv("BYES_RISK_DEPTH_OBS_WARN", "1.0")
    monkeypatch.setenv("BYES_RISK_DEPTH_OBS_CRIT", "0.6")
    monkeypatch.setenv("BYES_RISK_DEPTH_DROPOFF_DELTA", "0.8")

    payload = {"image_b64": _encode_image_b64(_blank_image()), "frameSeq": 2}

    monkeypatch.setenv("BYES_SERVICE_RISK_DEBUG", "1")
    _reset_service_globals()
    with TestClient(inference_app.app) as client:
        response = client.post("/risk", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert "debug" in body
        assert isinstance(body.get("debug"), dict)
        hazards = body.get("hazards", [])
        assert isinstance(hazards, list) and hazards
        assert hazards[0].get("hazardKind") == "dropoff"

    monkeypatch.setenv("BYES_SERVICE_RISK_DEBUG", "0")
    _reset_service_globals()
    with TestClient(inference_app.app) as client:
        response = client.post("/risk", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert "debug" not in body
