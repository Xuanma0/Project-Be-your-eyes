from __future__ import annotations

import base64
import os
import random
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


def _now_ms() -> int:
    return int(time.time() * 1000)


class InferenceRequest(BaseModel):
    image_b64: str
    frameSeq: int | None = None


app = FastAPI(title="BYES Reference Inference Service")


def _decode_image_b64(value: str) -> bytes:
    text = str(value or "").strip()
    if not text:
        return b""
    try:
        return base64.b64decode(text, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_image_b64:{exc.__class__.__name__}") from exc


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True}


@app.post("/ocr")
def infer_ocr(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    _decode_image_b64(request.image_b64)
    fail_prob = float(os.getenv("BYES_REF_OCR_FAIL_PROB", "0") or "0")
    if random.random() < max(0.0, min(1.0, fail_prob)):
        raise HTTPException(status_code=503, detail="ocr_unavailable")

    delay_ms = max(0, int(os.getenv("BYES_REF_OCR_DELAY_MS", "0") or "0"))
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    model = str(os.getenv("BYES_REF_OCR_MODEL_ID", "reference-ocr-v1")).strip() or "reference-ocr-v1"
    text = str(os.getenv("BYES_REF_OCR_TEXT", "EXIT")).strip() or "EXIT"
    if isinstance(request.frameSeq, int) and request.frameSeq % 2 == 0:
        text = str(os.getenv("BYES_REF_OCR_TEXT_ALT", text)).strip() or text
    latency_ms = max(0, _now_ms() - started)
    return {"text": text, "latencyMs": latency_ms, "model": model}


@app.post("/risk")
def infer_risk(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    _decode_image_b64(request.image_b64)
    fail_prob = float(os.getenv("BYES_REF_RISK_FAIL_PROB", "0") or "0")
    if random.random() < max(0.0, min(1.0, fail_prob)):
        raise HTTPException(status_code=503, detail="risk_unavailable")

    delay_ms = max(0, int(os.getenv("BYES_REF_RISK_DELAY_MS", "0") or "0"))
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    model = str(os.getenv("BYES_REF_RISK_MODEL_ID", "reference-risk-v1")).strip() or "reference-risk-v1"
    if isinstance(request.frameSeq, int) and request.frameSeq % 3 == 0:
        hazards = [{"hazardKind": "dropoff", "severity": "critical"}]
    else:
        hazards = [{"hazardKind": "stair_down", "severity": "warning"}]
    latency_ms = max(0, _now_ms() - started)
    return {"hazards": hazards, "latencyMs": latency_ms, "model": model}


# TODO: replace infer_ocr and infer_risk internals with real model pipelines:
# - OCR: PaddleOCR/Tesseract tokenizer + postprocess
# - Risk: depth model + hazard projection and thresholding
