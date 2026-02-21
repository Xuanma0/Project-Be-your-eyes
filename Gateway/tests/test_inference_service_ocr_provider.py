from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services.inference_service import app as inference_app


def _encode_image_b64() -> str:
    image = Image.new("RGB", (96, 96), (120, 120, 120))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _reset_ocr_provider_cache() -> None:
    inference_app._OCR_PROVIDER = None  # type: ignore[attr-defined]


def test_ocr_provider_http_requires_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("BYES_SERVICE_OCR_PROVIDER", "http")
    monkeypatch.delenv("BYES_SERVICE_OCR_ENDPOINT", raising=False)
    _reset_ocr_provider_cache()
    with pytest.raises(RuntimeError) as exc_info:
        inference_app.get_ocr_provider()
    assert "BYES_SERVICE_OCR_ENDPOINT" in str(exc_info.value)


def test_ocr_endpoint_returns_min_schema(monkeypatch) -> None:
    monkeypatch.setenv("BYES_SERVICE_OCR_PROVIDER", "mock")
    monkeypatch.setenv("BYES_SERVICE_OCR_MODEL_ID", "mock-ocr-v1")
    _reset_ocr_provider_cache()

    with TestClient(inference_app.app) as client:
        response = client.post(
            "/ocr",
            json={"image_b64": _encode_image_b64(), "frameSeq": 1, "runId": "fixture-ocr-gt"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()

    assert payload.get("schemaVersion") == "byes.ocr.v1"
    assert isinstance(payload.get("lines"), list)
    assert int(payload.get("linesCount", 0)) >= 1
    assert payload.get("model") == "mock-ocr-v1"
    assert "latencyMs" in payload
