from __future__ import annotations

import base64
import io
import os
import random
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel

from services.inference_service.providers.base import OCRProvider
from services.inference_service.providers.paddleocr_ocr import PaddleOcrProvider
from services.inference_service.providers.reference_ocr import ReferenceOcrProvider
from services.inference_service.providers.tesseract_ocr import TesseractOcrProvider
from services.inference_service.providers.utils import postprocess_text


def _now_ms() -> int:
    return int(time.time() * 1000)


class InferenceRequest(BaseModel):
    image_b64: str
    frameSeq: int | None = None


app = FastAPI(title="BYES Reference Inference Service")
_OCR_PROVIDER: OCRProvider | None = None


def _decode_image_b64(value: str) -> bytes:
    text = str(value or "").strip()
    if not text:
        return b""
    try:
        return base64.b64decode(text, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_image_b64:{exc.__class__.__name__}") from exc


def _decode_pil_image(value: str) -> Image.Image:
    raw = _decode_image_b64(value)
    if not raw:
        raise HTTPException(status_code=400, detail="empty_image_payload")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_image:{exc.__class__.__name__}") from exc


def _select_ocr_provider() -> OCRProvider:
    name = str(os.getenv("BYES_SERVICE_OCR_PROVIDER", "reference")).strip().lower()
    if name == "tesseract":
        return TesseractOcrProvider()
    if name == "paddleocr":
        return PaddleOcrProvider()
    return ReferenceOcrProvider()


def get_ocr_provider() -> OCRProvider:
    global _OCR_PROVIDER  # noqa: PLW0603
    if _OCR_PROVIDER is None:
        _OCR_PROVIDER = _select_ocr_provider()
        print(f"[inference_service] selected OCR provider={_OCR_PROVIDER.name} model={_OCR_PROVIDER.model}")
    return _OCR_PROVIDER


@app.on_event("startup")
def _startup_provider() -> None:
    get_ocr_provider()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    provider = get_ocr_provider()
    return {"ok": True, "ocrProvider": provider.name, "ocrModel": provider.model}


@app.post("/ocr")
def infer_ocr(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    image = _decode_pil_image(request.image_b64)
    fail_prob = float(os.getenv("BYES_SERVICE_OCR_FAIL_PROB", os.getenv("BYES_REF_OCR_FAIL_PROB", "0")) or "0")
    if random.random() < max(0.0, min(1.0, fail_prob)):
        raise HTTPException(status_code=503, detail="ocr_unavailable")

    delay_ms = max(0, int(os.getenv("BYES_SERVICE_OCR_DELAY_MS", os.getenv("BYES_REF_OCR_DELAY_MS", "0")) or "0"))
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    provider = get_ocr_provider()
    try:
        result = provider.infer(image, request.frameSeq)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"ocr_infer_failed:{exc.__class__.__name__}") from exc

    text = postprocess_text(str(result.get("text", "")))
    model = str(result.get("model", provider.model)).strip() or provider.model
    latency_ms = max(0, _now_ms() - started)
    return {"text": text, "latencyMs": latency_ms, "model": model}


@app.post("/risk")
def infer_risk(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    _decode_pil_image(request.image_b64)
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
