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


def _reset_seg_provider_cache() -> None:
    inference_app._SEG_PROVIDER = None  # type: ignore[attr-defined]


def test_seg_provider_http_requires_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("BYES_SERVICE_SEG_PROVIDER", "http")
    monkeypatch.delenv("BYES_SERVICE_SEG_ENDPOINT", raising=False)
    _reset_seg_provider_cache()
    with pytest.raises(RuntimeError) as exc_info:
        inference_app.get_seg_provider()
    assert "BYES_SERVICE_SEG_ENDPOINT" in str(exc_info.value)


def test_seg_endpoint_returns_min_schema(monkeypatch) -> None:
    monkeypatch.setenv("BYES_SERVICE_SEG_PROVIDER", "mock")
    monkeypatch.setenv("BYES_SERVICE_SEG_MODEL_ID", "mock-seg-v1")
    _reset_seg_provider_cache()

    with TestClient(inference_app.app) as client:
        response = client.post(
            "/seg",
            json={"image_b64": _encode_image_b64(), "frameSeq": 1, "targets": ["person", "stairs"]},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
    assert isinstance(payload.get("segments"), list)
    assert "latencyMs" in payload
    assert payload.get("model") == "mock-seg-v1"
    assert int(payload.get("targetsCount", 0)) == 2
    assert payload.get("targetsUsed") == ["person", "stairs"]
