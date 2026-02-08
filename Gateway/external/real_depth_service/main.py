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


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "real_depth", "ts": int(time.time() * 1000)}


@app.post("/infer")
async def infer_depth(
    image: UploadFile = File(...),
    meta: str | None = Form(None),
) -> dict[str, Any]:
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
