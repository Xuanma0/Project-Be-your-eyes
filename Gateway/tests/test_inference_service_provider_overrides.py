from __future__ import annotations

from fastapi.testclient import TestClient

from services.inference_service import app as inference_app


def _reset_provider_state() -> None:
    for key in list(inference_app._PROVIDER_OVERRIDES):  # noqa: SLF001
        inference_app._PROVIDER_OVERRIDES[key] = None  # noqa: SLF001
    inference_app._OCR_PROVIDER = None  # noqa: SLF001
    inference_app._RISK_PROVIDER = None  # noqa: SLF001
    inference_app._DEPTH_PROVIDER = None  # noqa: SLF001
    inference_app._SEG_PROVIDER = None  # noqa: SLF001
    inference_app._DET_PROVIDER = None  # noqa: SLF001
    inference_app._TOOL_DEPTH_PROVIDER = None  # noqa: SLF001
    inference_app._SLAM_PROVIDER = None  # noqa: SLF001
    inference_app._OCR_PROVIDER_KEY = None  # noqa: SLF001
    inference_app._RISK_PROVIDER_KEY = None  # noqa: SLF001
    inference_app._DEPTH_PROVIDER_KEY = None  # noqa: SLF001
    inference_app._SEG_PROVIDER_KEY = None  # noqa: SLF001
    inference_app._DET_PROVIDER_KEY = None  # noqa: SLF001
    inference_app._TOOL_DEPTH_PROVIDER_KEY = None  # noqa: SLF001
    inference_app._SLAM_PROVIDER_KEY = None  # noqa: SLF001


def test_inference_service_provider_overrides_roundtrip() -> None:
    _reset_provider_state()
    try:
        with TestClient(inference_app.app) as client:
            response = client.post(
                "/providers/overrides",
                json={
                    "det": {"backend": "yolo26"},
                    "seg": {"backend": "sam3"},
                    "depth": {"backend": "da3"},
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body.get("ok") is True
            providers = body.get("providers", {})
            assert providers.get("det", {}).get("backend") == "yolo26"
            assert providers.get("seg", {}).get("backend") == "sam3"
            assert providers.get("depthTool", {}).get("backend") == "da3"
            overrides = body.get("overrides", {})
            assert overrides.get("det") == "yolo26"
            assert overrides.get("seg") == "sam3"
            assert overrides.get("depth") == "da3"

            response_2 = client.get("/providers")
            assert response_2.status_code == 200
            body_2 = response_2.json()
            assert body_2.get("ok") is True
            assert body_2.get("providers", {}).get("det", {}).get("backend") == "yolo26"
    finally:
        _reset_provider_state()
