from __future__ import annotations

import io

from fastapi.testclient import TestClient

from byes.inference.backends.mock import MockDetBackend
from main import app, gateway


def test_ui_state_includes_provider_runtime_evidence() -> None:
    original_enable_det = gateway.config.inference_enable_det
    original_det_backend = gateway.det_backend
    object.__setattr__(gateway.config, "inference_enable_det", True)
    gateway.det_backend = MockDetBackend(model_id="mock-det-ui-state")
    gateway.drain_inference_events()
    try:
        with TestClient(app) as client:
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            frame_resp = client.post("/api/frame", files=files)
            assert frame_resp.status_code == 200

            providers_resp = client.get("/api/providers")
            assert providers_resp.status_code == 200
            providers_payload = providers_resp.json()
            runtime = providers_payload.get("runtimeEvidence", {})
            assert isinstance(runtime, dict)
            assert isinstance(runtime.get("det"), dict)
            assert runtime.get("det", {}).get("backend")

            ui_state_resp = client.get("/api/ui/state")
            assert ui_state_resp.status_code == 200
            ui_state = ui_state_resp.json()
            caps = ui_state.get("capabilities", {})
            providers = caps.get("available_providers", {})
            det_row = providers.get("det", {})
            assert isinstance(det_row, dict)
            assert det_row.get("backend")
            runtime_row = det_row.get("runtime", {})
            assert isinstance(runtime_row, dict)
            assert runtime_row.get("backend")
            assert "isMock" in runtime_row
    finally:
        object.__setattr__(gateway.config, "inference_enable_det", original_enable_det)
        gateway.det_backend = original_det_backend
        gateway.drain_inference_events()
