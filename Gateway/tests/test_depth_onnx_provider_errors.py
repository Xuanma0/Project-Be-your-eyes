from __future__ import annotations

import importlib.util

import pytest

from services.inference_service.providers.onnx_depth import OnnxDepthProvider


def test_onnx_provider_errors_when_onnxruntime_missing(monkeypatch, tmp_path) -> None:
    if importlib.util.find_spec("onnxruntime") is not None:
        pytest.skip("onnxruntime is installed in this environment")

    fake_model = tmp_path / "model.onnx"
    fake_model.write_bytes(b"onnx-placeholder")
    monkeypatch.setenv("BYES_SERVICE_DEPTH_ONNX_PATH", str(fake_model))

    with pytest.raises(RuntimeError) as exc:
        OnnxDepthProvider()
    assert "requirements-onnx-depth.txt" in str(exc.value)


def test_onnx_provider_errors_when_model_path_missing_if_onnxruntime_installed(monkeypatch) -> None:
    if importlib.util.find_spec("onnxruntime") is None:
        pytest.skip("onnxruntime not installed; path-missing branch is not reachable")

    monkeypatch.delenv("BYES_SERVICE_DEPTH_ONNX_PATH", raising=False)
    with pytest.raises(RuntimeError) as exc:
        OnnxDepthProvider()
    assert "BYES_SERVICE_DEPTH_ONNX_PATH" in str(exc.value)
