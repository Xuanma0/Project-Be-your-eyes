from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


def _load_external_app(service_name: str) -> Any:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "external" / service_name / "main.py"
    spec = importlib.util.spec_from_file_location(f"byes_ext_{service_name}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load external service module: {service_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = getattr(module, "app", None)
    if app is None:
        raise RuntimeError(f"module has no FastAPI app: {service_name}")
    return app


def test_external_healthz_contract_mock_backend(monkeypatch) -> None:
    monkeypatch.setenv("BYES_BACKEND", "mock")
    monkeypatch.setenv("BYES_MODEL_ID", "contract-test-model")
    monkeypatch.setenv("BYES_WEIGHTS_DIR", "/tmp/byes-models")

    service_names = [
        "real_det_service",
        "real_ocr_service",
        "real_depth_service",
        "real_vlm_service",
    ]
    for service_name in service_names:
        app = _load_external_app(service_name)
        with TestClient(app) as client:
            response = client.get("/healthz")
            assert response.status_code == 200
            payload = response.json()
            assert isinstance(payload, dict)
            assert payload.get("ready") is True
            assert payload.get("warmed_up") is True
            assert payload.get("backend") == "mock"
            assert isinstance(payload.get("model_id"), str)
            assert isinstance(payload.get("version"), str)
