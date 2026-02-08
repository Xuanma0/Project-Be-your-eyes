from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def _load_det_service_app() -> Any:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "external" / "real_det_service" / "main.py"
    module_name = f"byes_real_det_service_{module_path.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load real_det_service module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = getattr(module, "app", None)
    if app is None:
        raise RuntimeError("real_det_service module has no FastAPI app")
    return app


def _create_tiny_det_model(path: Path) -> None:
    onnx = pytest.importorskip("onnx")
    np = pytest.importorskip("numpy")

    helper = onnx.helper
    numpy_helper = onnx.numpy_helper

    path.parent.mkdir(parents=True, exist_ok=True)
    input_tensor = helper.make_tensor_value_info("images", onnx.TensorProto.FLOAT, [1, 3, 64, 64])
    output_tensor = helper.make_tensor_value_info("output0", onnx.TensorProto.FLOAT, [1, 1, 6])

    const_det = np.array([[[16.0, 16.0, 48.0, 48.0, 0.95, 0.0]]], dtype=np.float32)
    const_zero = np.array([0.0], dtype=np.float32)

    nodes = [
        helper.make_node("Constant", inputs=[], outputs=["const_det"], value=numpy_helper.from_array(const_det)),
        helper.make_node("Constant", inputs=[], outputs=["const_zero"], value=numpy_helper.from_array(const_zero)),
        helper.make_node("ReduceMean", inputs=["images"], outputs=["mean_out"], keepdims=1),
        helper.make_node("Mul", inputs=["mean_out", "const_zero"], outputs=["scaled_zero"]),
        helper.make_node("Add", inputs=["const_det", "scaled_zero"], outputs=["output0"]),
    ]
    graph = helper.make_graph(nodes, "tiny_det_graph", [input_tensor], [output_tensor])
    model = helper.make_model(graph, producer_name="byes-tests", opset_imports=[helper.make_operatorsetid("", 13)])
    onnx.save(model, str(path))


def _fake_image_bytes() -> bytes:
    image = Image.new("RGB", (96, 96), color=(120, 130, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_real_det_service_healthz_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("onnxruntime")

    model_id = "test-real-det-ready"
    weights_root = tmp_path / "weights"
    model_path = weights_root / model_id / "model.onnx"

    monkeypatch.setenv("BYES_BACKEND", "onnxruntime")
    monkeypatch.setenv("BYES_MODEL_ID", model_id)
    monkeypatch.setenv("BYES_WEIGHTS_DIR", str(weights_root))
    monkeypatch.setenv("BYES_MODEL_FILE", "model.onnx")

    app_missing = _load_det_service_app()
    with TestClient(app_missing) as client:
        healthz_missing = client.get("/healthz")
        assert healthz_missing.status_code == 200
        payload_missing = healthz_missing.json()
        assert payload_missing.get("ready") is False
        assert payload_missing.get("warmed_up") is False
        assert str(payload_missing.get("reason", "")).startswith("weights_missing")

    _create_tiny_det_model(model_path)

    app_ready = _load_det_service_app()
    with TestClient(app_ready) as client:
        healthz_ready = client.get("/healthz")
        assert healthz_ready.status_code == 200
        payload_ready = healthz_ready.json()
        assert payload_ready.get("ready") is True
        assert payload_ready.get("warmed_up") is True
        assert payload_ready.get("backend") == "onnxruntime"
        assert payload_ready.get("model_id") == model_id

        response = client.post(
            "/infer",
            files={"image": ("frame.jpg", _fake_image_bytes(), "image/jpeg")},
            data={"tasks": "[\"det\"]"},
        )
        assert response.status_code == 200
        result = response.json()
        detections = result.get("detections")
        assert isinstance(detections, list)
