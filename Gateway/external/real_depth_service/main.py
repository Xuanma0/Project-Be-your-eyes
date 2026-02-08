from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile


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


app = FastAPI(title="BeYourEyes RealDepth Mock Service")
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
    model_id = _env_str("BYES_MODEL_ID", "byes-real-depth-v1")
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
    return {"ok": True, "service": "real_depth", "ts": int(time.time() * 1000)}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "ready": bool(_STATE.get("ready", False)),
        "model_id": str(_STATE.get("model_id", "")),
        "backend": str(_STATE.get("backend", "mock")),
        "version": str(_STATE.get("version", _SERVICE_VERSION)),
        "warmed_up": bool(_STATE.get("warmed_up", False)),
    }


@app.post("/infer")
async def infer_depth(
    image: UploadFile = File(...),
    meta: str | None = Form(None),
) -> dict[str, Any]:
    _ensure_ready()
    started = time.perf_counter()
    payload = await image.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty image payload")

    _ = meta  # Reserved for future spatial alignment usage.

    delay_ms = max(0, _env_int("DELAY_MS", 120))
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)

    fail_prob = max(0.0, min(1.0, _env_float("FAIL_PROB", 0.0)))
    if fail_prob > 0 and random.random() < fail_prob:
        # Simulate a hanging inference so gateway timeout/degradation path can be validated.
        await asyncio.sleep(30.0)

    hazards = [
        {
            "distanceM": 1.2,
            "azimuthDeg": 3.0,
            "confidence": 0.88,
            "kind": os.getenv("DEPTH_PRIMARY_KIND", "obstacle"),
        },
        {
            "distanceM": 2.6,
            "azimuthDeg": -42.0,
            "confidence": 0.72,
            "kind": "wall",
        },
    ]
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "hazards": hazards,
        "model": os.getenv("DEPTH_MODEL", "mock_depth_v1"),
        "latencyMs": latency_ms,
    }
