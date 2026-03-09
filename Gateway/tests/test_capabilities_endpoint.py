from __future__ import annotations

from fastapi.testclient import TestClient

from main import app, gateway


def test_api_capabilities_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/api/capabilities")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        assert isinstance(body.get("version"), str)
        assert isinstance(body.get("available_providers"), dict)
        providers = body["available_providers"]
        assert "ocr" in providers
        assert "risk" in providers
        assert "det" in providers
        assert "depth" in providers
        assert "seg" in providers
        assert "slam" in providers
        assert isinstance(body.get("enabled_flags"), dict)
        assert "det" in body["enabled_flags"]


def test_api_capabilities_reflects_det_flag() -> None:
    original_det = gateway.config.inference_enable_det
    try:
        object.__setattr__(gateway.config, "inference_enable_det", True)
        with TestClient(app) as client:
            response = client.get("/api/capabilities")
            assert response.status_code == 200
            body = response.json()
            providers = body.get("available_providers", {})
            assert providers.get("det", {}).get("enabled") is True
            assert body.get("enabled_flags", {}).get("det") is True
    finally:
        object.__setattr__(gateway.config, "inference_enable_det", original_det)
