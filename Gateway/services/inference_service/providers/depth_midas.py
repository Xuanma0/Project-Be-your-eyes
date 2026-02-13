from __future__ import annotations

import os
from typing import Any

from PIL import Image

from services.inference_service.providers.depth_base import DepthMap


class MidasOnnxDepthProvider:
    """Optional ONNX depth provider (loaded only when explicitly selected)."""

    name = "midas"

    def __init__(self) -> None:
        override = str(os.getenv("BYES_SERVICE_DEPTH_MODEL_ID", "")).strip()
        self.model = override or "midas-small-onnx"
        self.model_path = str(os.getenv("BYES_SERVICE_DEPTH_MODEL_PATH", "")).strip()
        self.input_size = max(64, int(os.getenv("BYES_SERVICE_DEPTH_INPUT_SIZE", "256") or "256"))
        self._session: Any | None = None

    def infer_depth(self, image: Image.Image, frame_seq: int | None = None) -> DepthMap:
        del frame_seq
        session = self._get_session()
        np = self._np_module()

        rgb = image.convert("RGB").resize((self.input_size, self.input_size), Image.Resampling.BILINEAR)
        arr = np.asarray(rgb, dtype=np.float32) / 255.0
        chw = np.transpose(arr, (2, 0, 1))
        x = np.expand_dims(chw, axis=0).astype(np.float32)

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: x})
        if not outputs:
            raise RuntimeError("depth_infer_no_output")
        out = outputs[0]
        out_arr = np.asarray(out, dtype=np.float32).squeeze()
        if out_arr.ndim != 2:
            raise RuntimeError("depth_output_invalid_shape")
        if out_arr.size == 0:
            raise RuntimeError("depth_output_empty")

        min_val = float(np.nanmin(out_arr))
        max_val = float(np.nanmax(out_arr))
        if not np.isfinite(min_val) or not np.isfinite(max_val):
            raise RuntimeError("depth_output_non_finite")
        depth = out_arr.tolist()
        return {
            "depth": depth,
            "min": min_val,
            "max": max_val,
            "scale": "relative",
            "width": int(out_arr.shape[1]),
            "height": int(out_arr.shape[0]),
            "model": self.model,
        }

    def _get_session(self) -> Any:
        if self._session is not None:
            return self._session
        if not self.model_path:
            raise RuntimeError("depth_model_path_missing")
        try:
            import onnxruntime as ort  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"onnxruntime_import_failed:{exc.__class__.__name__}") from exc
        self._session = ort.InferenceSession(self.model_path, providers=["CPUExecutionProvider"])
        return self._session

    @staticmethod
    def _np_module() -> Any:
        try:
            import numpy as np  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"numpy_import_failed:{exc.__class__.__name__}") from exc
        return np
