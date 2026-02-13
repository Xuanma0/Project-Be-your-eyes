from __future__ import annotations

import asyncio
import io
import os
import random
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile


def _now_ms() -> int:
    return int(time.time() * 1000)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return str(raw).strip() if raw is not None else default


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class OnnxOcrRuntime:
    def __init__(self, model_path: Path) -> None:
        import numpy as np
        import onnxruntime as ort

        self._np = np
        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        input_meta = self._session.get_inputs()[0]
        self._input_name = input_meta.name
        shape = list(input_meta.shape)
        height = shape[2] if len(shape) > 2 and isinstance(shape[2], int) else _env_int("BYES_OCR_INPUT_H", 384)
        width = shape[3] if len(shape) > 3 and isinstance(shape[3], int) else _env_int("BYES_OCR_INPUT_W", 384)
        self._input_h = max(32, int(height))
        self._input_w = max(32, int(width))

    def warmup(self) -> None:
        sample = self._np.zeros((1, 3, self._input_h, self._input_w), dtype=self._np.float32)
        _ = self._session.run(None, {self._input_name: sample})

    def infer(self, image_bytes: bytes) -> dict[str, Any]:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        resized = image.resize((self._input_w, self._input_h))
        arr = self._np.asarray(resized, dtype=self._np.float32) / 255.0
        tensor = self._np.transpose(arr, (2, 0, 1))[None, ...]
        outputs = self._session.run(None, {self._input_name: tensor})

        signal = 0.0
        for output in outputs:
            if not hasattr(output, "size"):
                continue
            if int(output.size) <= 0:
                continue
            signal += float(self._np.mean(self._np.abs(output)))
        signal = max(0.0, signal)

        threshold = max(0.0, _env_float("BYES_OCR_SIGNAL_THRESHOLD", 0.02))
        if signal < threshold:
            return {"lines": [], "summary": "No readable text detected", "confidence": 0.25}

        text = _env_str("BYES_OCR_DEFAULT_TEXT", "TEXT DETECTED")
        confidence = _clamp01(0.55 + min(signal, 1.0) * 0.35)
        lines = [{"text": text, "score": round(confidence, 4), "box": [0.12, 0.22, 0.86, 0.42]}]
        return {"lines": lines, "summary": f"Detected text: {text}", "confidence": confidence}


app = FastAPI(title="BeYourEyes RealOCR Service")
_SERVICE_VERSION = "0.3.0"
_STATE: dict[str, Any] = {
    "ready": False,
    "warmed_up": False,
    "model_id": "",
    "backend": "mock",
    "version": _SERVICE_VERSION,
    "reason": "startup",
    "model_path": "",
}
_RUNTIME: OnnxOcrRuntime | None = None


def _build_runtime_state() -> dict[str, Any]:
    global _RUNTIME
    backend = _env_str("BYES_BACKEND", "mock").lower()
    model_id = _env_str("BYES_MODEL_ID", "byes-real-ocr-onnx-cpu-v1")
    weights_dir = Path(_env_str("BYES_WEIGHTS_DIR", "/models"))
    model_file = _env_str("BYES_MODEL_FILE", "model.onnx")
    explicit_model_path = _env_str("BYES_MODEL_PATH", "")
    model_path = Path(explicit_model_path) if explicit_model_path else (weights_dir / model_id / model_file)

    state: dict[str, Any] = {
        "ready": False,
        "warmed_up": False,
        "model_id": model_id,
        "backend": backend,
        "version": _SERVICE_VERSION,
        "reason": "startup",
        "model_path": str(model_path),
    }

    if backend == "mock":
        _RUNTIME = None
        state["ready"] = True
        state["warmed_up"] = True
        state["reason"] = "ok"
        return state

    if backend not in {"onnxruntime", "onnx", "ort"}:
        _RUNTIME = None
        state["reason"] = "unsupported_backend"
        return state

    if not model_path.exists():
        _RUNTIME = None
        state["reason"] = "weights_missing"
        return state

    try:
        runtime = OnnxOcrRuntime(model_path=model_path)
        runtime.warmup()
        _RUNTIME = runtime
        state["ready"] = True
        state["warmed_up"] = True
        state["reason"] = "ok"
        return state
    except Exception as exc:  # noqa: BLE001
        _RUNTIME = None
        state["reason"] = f"load_error:{exc.__class__.__name__}"
        return state


@app.on_event("startup")
async def _startup() -> None:
    _STATE.update(_build_runtime_state())


def _ensure_ready() -> None:
    if not bool(_STATE.get("ready", False)):
        raise HTTPException(status_code=503, detail="service_not_ready")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "real_ocr", "ts": _now_ms()}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "ready": bool(_STATE.get("ready", False)),
        "model_id": str(_STATE.get("model_id", "")),
        "backend": str(_STATE.get("backend", "mock")),
        "version": str(_STATE.get("version", _SERVICE_VERSION)),
        "warmed_up": bool(_STATE.get("warmed_up", False)),
        "reason": str(_STATE.get("reason", "")),
    }


@app.post("/infer/ocr")
async def infer_ocr(image: UploadFile = File(...)) -> dict[str, Any]:
    _ensure_ready()
    started = time.perf_counter()
    payload = await image.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty image payload")

    timeout_prob = max(0.0, min(1.0, _env_float("OCR_TIMEOUT_PROB", 0.0)))
    if timeout_prob > 0.0 and random.random() < timeout_prob:
        await asyncio.sleep(30.0)

    sleep_ms = max(0, _env_int("OCR_SLEEP_MS", 80))
    if sleep_ms > 0:
        await asyncio.sleep(sleep_ms / 1000.0)

    if str(_STATE.get("backend", "mock")).lower() == "mock":
        confidence = _clamp01(_env_float("OCR_MOCK_CONFIDENCE", 0.88))
        lines = [
            {"text": "EXIT", "score": round(confidence, 4), "box": [0.12, 0.18, 0.42, 0.31]},
            {"text": "ROOM 203", "score": round(max(0.0, confidence - 0.06), 4), "box": [0.15, 0.36, 0.55, 0.48]},
        ]
        summary = "Detected text: EXIT, ROOM 203"
    else:
        if _RUNTIME is None:
            raise HTTPException(status_code=503, detail="runtime_not_initialized")
        runtime_result = await asyncio.to_thread(_RUNTIME.infer, payload)
        lines = runtime_result.get("lines", [])
        summary = str(runtime_result.get("summary", "")).strip()
        if not summary:
            summary = "No readable text detected"

    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "lines": lines,
        "summary": summary,
        "latencyMs": latency_ms,
        "model_id": _STATE.get("model_id", ""),
        "backend": _STATE.get("backend", "mock"),
    }
