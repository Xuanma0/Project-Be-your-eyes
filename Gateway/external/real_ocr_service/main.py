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


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "real_ocr", "ts": int(time.time() * 1000)}


@app.post("/infer/ocr")
async def infer_ocr(image: UploadFile = File(...)) -> dict[str, Any]:
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
