from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile


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


app = FastAPI(title="BeYourEyes RealOCR Service")
_SERVICE_VERSION = "0.2.1"
_STATE: dict[str, Any] = {
    "ready": False,
    "warmed_up": False,
    "model_id": "",
    "backend": "mock",
    "version": _SERVICE_VERSION,
}


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return str(raw).strip() if raw is not None else default


def _build_runtime_state() -> dict[str, Any]:
    backend = _env_str("BYES_BACKEND", "mock").lower()
    model_id = _env_str("BYES_MODEL_ID", "byes-real-ocr-v1")
    _weights_dir = _env_str("BYES_WEIGHTS_DIR", "/models")
    ready = backend in {"mock", "torch", "onnx"}
    warmed_up = ready
    return {
        "ready": ready,
        "warmed_up": warmed_up,
        "model_id": model_id,
        "backend": backend,
        "version": _SERVICE_VERSION,
    }


@app.on_event("startup")
async def _startup() -> None:
    _STATE.update(_build_runtime_state())


def _ensure_ready() -> None:
    if not bool(_STATE.get("ready", False)):
        raise HTTPException(status_code=503, detail="service_not_ready")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "real_ocr", "ts": int(time.time() * 1000)}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "ready": bool(_STATE.get("ready", False)),
        "model_id": str(_STATE.get("model_id", "")),
        "backend": str(_STATE.get("backend", "mock")),
        "version": str(_STATE.get("version", _SERVICE_VERSION)),
        "warmed_up": bool(_STATE.get("warmed_up", False)),
    }


@app.post("/infer/ocr")
async def infer_ocr(image: UploadFile = File(...)) -> dict[str, Any]:
    _ensure_ready()
    started = time.perf_counter()
    payload = await image.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty image payload")

    timeout_prob = max(0.0, min(1.0, _env_float("OCR_TIMEOUT_PROB", 0.0)))
    if timeout_prob > 0 and random.random() < timeout_prob:
        # Simulate hanging downstream OCR. Gateway timeout should enforce cutoff.
        await asyncio.sleep(30.0)

    sleep_ms = max(0, _env_int("OCR_SLEEP_MS", 80))
    if sleep_ms > 0:
        await asyncio.sleep(sleep_ms / 1000.0)

    lines = [
        {"text": "EXIT", "score": 0.93, "box": [0.12, 0.18, 0.42, 0.31]},
        {"text": "ROOM 203", "score": 0.88, "box": [0.15, 0.36, 0.55, 0.48]},
    ]
    summary = "Detected text: EXIT, ROOM 203"
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "lines": lines,
        "summary": summary,
        "latencyMs": latency_ms,
    }
