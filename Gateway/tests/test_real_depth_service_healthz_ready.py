from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def _load_depth_service_app() -> Any:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "external" / "real_depth_service" / "main.py"
    module_name = f"byes_real_depth_service_{module_path.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load real_depth_service module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = getattr(module, "app", None)
    if app is None:
        raise RuntimeError("real_depth_service module has no FastAPI app")
    return app


def _create_tiny_onnx_model(path: Path) -> None:
    onnx = pytest.importorskip("onnx")
    np = pytest.importorskip("numpy")

    helper = onnx.helper
    numpy_helper = onnx.numpy_helper
    path.parent.mkdir(parents=True, exist_ok=True)

    input_tensor = helper.make_tensor_value_info("images", onnx.TensorProto.FLOAT, [1, 3, 64, 64])
    output_tensor = helper.make_tensor_value_info("output0", onnx.TensorProto.FLOAT, [1, 1, 1, 1])
    const_out = np.array([[[[0.9]]]], dtype=np.float32)

    nodes = [
        helper.make_node("Constant", inputs=[], outputs=["output0"], value=numpy_helper.from_array(const_out)),
    ]
    graph = helper.make_graph(nodes, "tiny_depth_graph", [input_tensor], [output_tensor])
    model = helper.make_model(graph, producer_name="byes-tests", opset_imports=[helper.make_operatorsetid("", 13)])
    onnx.save(model, str(path))


def _fake_image_bytes() -> bytes:
    image = Image.new("RGB", (96, 96), color=(140, 120, 130))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_real_depth_service_healthz_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("onnxruntime")
    model_id = "test-real-depth-ready"
    weights_root = tmp_path / "weights"
    model_path = weights_root / model_id / "model.onnx"

    monkeypatch.setenv("BYES_BACKEND", "onnxruntime")
    monkeypatch.setenv("BYES_MODEL_ID", model_id)
    monkeypatch.setenv("BYES_WEIGHTS_DIR", str(weights_root))
    monkeypatch.setenv("BYES_MODEL_FILE", "model.onnx")

    app_missing = _load_depth_service_app()
    with TestClient(app_missing) as client:
        healthz_missing = client.get("/healthz")
        assert healthz_missing.status_code == 200
        payload_missing = healthz_missing.json()
        assert payload_missing.get("ready") is False
        assert payload_missing.get("warmed_up") is False
        assert str(payload_missing.get("reason", "")).startswith("weights_missing")
        infer_missing = client.post("/infer", files={"image": ("frame.jpg", _fake_image_bytes(), "image/jpeg")})
        assert infer_missing.status_code == 503

    _create_tiny_onnx_model(model_path)
    app_ready = _load_depth_service_app()
    with TestClient(app_ready) as client:
        healthz_ready = client.get("/healthz")
        assert healthz_ready.status_code == 200
        payload_ready = healthz_ready.json()
        assert payload_ready.get("ready") is True
        assert payload_ready.get("warmed_up") is True
        assert payload_ready.get("backend") == "onnxruntime"
        assert payload_ready.get("model_id") == model_id

        infer_ready = client.post("/infer", files={"image": ("frame.jpg", _fake_image_bytes(), "image/jpeg")})
        assert infer_ready.status_code == 200
        result = infer_ready.json()
        assert isinstance(result.get("hazards"), list)
        assert "latencyMs" in result
