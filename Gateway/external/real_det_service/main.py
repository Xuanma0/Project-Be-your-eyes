from __future__ import annotations

import json
import os
import random
import time
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile


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


app = FastAPI(title="BeYourEyes RealDet Mock Service")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ts": _now_ms()}


@app.post("/infer")
async def infer(
    image: UploadFile = File(...),
    roi: str | None = Form(None),
    tasks: str | None = Form(None),
) -> dict[str, Any]:
    _ = await image.read()
    delay_ms = max(0, _env_int("REAL_DET_DELAY_MS", 80))
    timeout_prob = max(0.0, min(1.0, _env_float("REAL_DET_TIMEOUT_PROB", 0.0)))
    if delay_ms > 0:
        await _sleep_ms(delay_ms)

    if timeout_prob > 0.0 and random.random() < timeout_prob:
        # Simulate long server stall to trigger client timeout.
        await _sleep_ms(max(1000, delay_ms * 8))

    parsed_roi: dict[str, Any] | None = None
    if roi:
        try:
            parsed = json.loads(roi)
            if isinstance(parsed, dict):
                parsed_roi = parsed
        except json.JSONDecodeError:
            parsed_roi = None

    parsed_tasks: list[str] = []
    if tasks:
        try:
            parsed = json.loads(tasks)
            if isinstance(parsed, list):
                parsed_tasks = [str(item) for item in parsed]
        except json.JSONDecodeError:
            parsed_tasks = []

    conf = max(0.1, min(0.99, _env_float("REAL_DET_CONFIDENCE", 0.86)))
    detections = [
        {
            "class": os.getenv("REAL_DET_CLASS", "door"),
            "bbox": [0.30, 0.18, 0.64, 0.82],
            "confidence": conf,
        }
    ]
    return {
        "detections": detections,
        "summary": f"Detected {detections[0]['class']}",
        "coordFrame": "World",
        "roi": parsed_roi,
        "tasks": parsed_tasks,
    }


async def _sleep_ms(delay_ms: int) -> None:
    import asyncio

    await asyncio.sleep(delay_ms / 1000.0)
