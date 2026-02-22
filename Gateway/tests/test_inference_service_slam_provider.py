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


def _reset_slam_provider_cache() -> None:
    inference_app._SLAM_PROVIDER = None  # type: ignore[attr-defined]


def test_slam_provider_http_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_SERVICE_SLAM_PROVIDER", "http")
    monkeypatch.delenv("BYES_SERVICE_SLAM_ENDPOINT", raising=False)
    _reset_slam_provider_cache()
    with pytest.raises(RuntimeError) as exc_info:
        inference_app.get_slam_provider()
    assert "BYES_SERVICE_SLAM_ENDPOINT" in str(exc_info.value)


def test_slam_pose_endpoint_returns_min_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_SERVICE_SLAM_PROVIDER", "mock")
    monkeypatch.setenv("BYES_SERVICE_SLAM_MODEL_ID", "mock-slam-v1")
    _reset_slam_provider_cache()

    with TestClient(inference_app.app) as client:
        response = client.post(
            "/slam/pose",
            json={"image_b64": _encode_image_b64(), "frameSeq": 1, "runId": "fixture-slam-gt"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()

    assert payload.get("schemaVersion") == "byes.slam_pose.v1"
    assert payload.get("model") == "mock-slam-v1"
    assert str(payload.get("trackingState", "")).strip()
    pose = payload.get("pose", {})
    assert isinstance(pose, dict)
    assert isinstance(pose.get("t"), list) and len(pose.get("t", [])) == 3
    assert isinstance(pose.get("q"), list) and len(pose.get("q", [])) == 4
    assert "latencyMs" in payload

