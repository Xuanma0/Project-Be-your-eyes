from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from PIL import Image

from services.inference_service.providers.depth_base import DepthMap


class OnnxDepthProvider:
    """Optional ONNX depth provider for Depth Anything V2 Small."""

    name = "onnx"

    def __init__(self) -> None:
        override = str(os.getenv("BYES_SERVICE_DEPTH_MODEL_ID", "")).strip()
        self.model = override or "depth-anything-v2-small-onnx"
        self.input_size = max(64, int(str(os.getenv("BYES_SERVICE_DEPTH_INPUT_SIZE", "256") or "256").strip()))
        self.model_path = self._resolve_model_path()
        self._session: Any | None = None

    def infer_depth(self, image: Image.Image, frame_seq: int | None = None) -> DepthMap:
        del frame_seq
        np = self._require_numpy()
        session = self._get_session()

        width, height = image.size
        if width <= 0 or height <= 0:
            raise RuntimeError("depth_input_invalid_image_size")

        rgb = image.convert("RGB")
        resized = rgb.resize((self.input_size, self.input_size), Image.Resampling.BILINEAR)

        arr = np.asarray(resized, dtype=np.float32) / 255.0
        mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        chw = np.transpose(arr, (2, 0, 1))
        x = np.expand_dims(chw, axis=0).astype(np.float32)

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: x})
        if not outputs:
            raise RuntimeError("depth_onnx_no_output")

        out = np.asarray(outputs[0], dtype=np.float32)
        out = np.squeeze(out)
        if out.ndim != 2:
            raise RuntimeError(f"depth_onnx_invalid_output_shape:{tuple(int(v) for v in out.shape)}")
        if out.size == 0:
            raise RuntimeError("depth_onnx_empty_output")

        finite = np.isfinite(out)
        if not finite.any():
            raise RuntimeError("depth_onnx_non_finite_output")

        safe_out = np.where(finite, out, np.nan)
        min_raw = float(np.nanmin(safe_out))
        max_raw = float(np.nanmax(safe_out))
        if max_raw - min_raw < 1e-9:
            normalized = np.zeros_like(safe_out, dtype=np.float32)
        else:
            normalized = (safe_out - min_raw) / (max_raw - min_raw)
        normalized = np.clip(normalized, 0.0, 1.0).astype(np.float32)

        # Depth Anything outputs are generally inverse-depth-like; invert so bigger means farther.
        distance = 1.0 - normalized
        distance = np.where(np.isfinite(distance), distance, 0.0).astype(np.float32)

        depth_small = Image.fromarray(distance, mode="F")
        depth_resized = depth_small.resize((width, height), Image.Resampling.BILINEAR)
        depth = np.asarray(depth_resized, dtype=np.float32)
        depth = np.where(np.isfinite(depth), depth, 0.0).astype(np.float32)

        min_val = float(np.min(depth)) if depth.size else 0.0
        max_val = float(np.max(depth)) if depth.size else 0.0
        return {
            "depth": depth.tolist(),
            "min": min_val,
            "max": max_val,
            "scale": "relative_distance_0_1",
            "width": int(width),
            "height": int(height),
            "model": self.model,
        }

    def _get_session(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            import onnxruntime as ort  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "onnxruntime is not installed; install optional deps with "
                "pip install -r Gateway/services/inference_service/requirements-onnx-depth.txt"
            ) from exc
        self._session = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
        return self._session

    @staticmethod
    def _require_numpy() -> Any:
        try:
            import numpy as np  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "numpy is required for ONNX depth provider; install optional deps with "
                "pip install -r Gateway/services/inference_service/requirements-onnx-depth.txt"
            ) from exc
        return np

    @staticmethod
    def _resolve_model_path() -> Path:
        if importlib.util.find_spec("onnxruntime") is None:
            raise RuntimeError(
                "onnxruntime is not installed; install optional deps with "
                "pip install -r Gateway/services/inference_service/requirements-onnx-depth.txt"
            )
        raw = str(os.getenv("BYES_SERVICE_DEPTH_ONNX_PATH", "")).strip()
        if not raw:
            raise RuntimeError("BYES_SERVICE_DEPTH_ONNX_PATH is required when BYES_SERVICE_DEPTH_PROVIDER=onnx")
        path = Path(raw).expanduser()
        if not path.exists() or not path.is_file():
            raise RuntimeError(
                f"BYES_SERVICE_DEPTH_ONNX_PATH points to a missing file: {path}. "
                "Set BYES_SERVICE_DEPTH_ONNX_PATH to an existing .onnx model path."
            )
        return path
