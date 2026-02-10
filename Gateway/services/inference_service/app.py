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

from services.inference_service.providers.base import OCRProvider, RiskProvider
from services.inference_service.providers.depth_base import DepthProvider
from services.inference_service.providers.depth_none import NoneDepthProvider
from services.inference_service.providers.depth_synth import SynthDepthProvider
from services.inference_service.providers.heuristic_risk import HeuristicRiskProvider
from services.inference_service.providers.paddleocr_ocr import PaddleOcrProvider
from services.inference_service.providers.reference_ocr import ReferenceOcrProvider
from services.inference_service.providers.reference_risk import ReferenceRiskProvider
from services.inference_service.providers.tesseract_ocr import TesseractOcrProvider
from services.inference_service.providers.utils import postprocess_text


def _now_ms() -> int:
    return int(time.time() * 1000)


class InferenceRequest(BaseModel):
    image_b64: str
    frameSeq: int | None = None


app = FastAPI(title="BYES Reference Inference Service")
_OCR_PROVIDER: OCRProvider | None = None
_RISK_PROVIDER: RiskProvider | None = None
_DEPTH_PROVIDER: DepthProvider | None = None


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


def _select_risk_provider() -> RiskProvider:
    name = str(os.getenv("BYES_SERVICE_RISK_PROVIDER", "reference")).strip().lower()
    if name == "heuristic":
        return HeuristicRiskProvider(depth_provider=get_depth_provider())
    return ReferenceRiskProvider()


def _select_depth_provider() -> DepthProvider:
    name = str(os.getenv("BYES_SERVICE_DEPTH_PROVIDER", "none")).strip().lower()
    if name == "synth":
        return SynthDepthProvider()
    if name == "midas":
        try:
            from services.inference_service.providers.depth_midas import MidasOnnxDepthProvider
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"depth_provider_import_failed:{exc.__class__.__name__}") from exc
        return MidasOnnxDepthProvider()
    return NoneDepthProvider()


def get_ocr_provider() -> OCRProvider:
    global _OCR_PROVIDER  # noqa: PLW0603
    if _OCR_PROVIDER is None:
        _OCR_PROVIDER = _select_ocr_provider()
        print(f"[inference_service] selected OCR provider={_OCR_PROVIDER.name} model={_OCR_PROVIDER.model}")
    return _OCR_PROVIDER


def get_risk_provider() -> RiskProvider:
    global _RISK_PROVIDER  # noqa: PLW0603
    if _RISK_PROVIDER is None:
        _RISK_PROVIDER = _select_risk_provider()
        print(f"[inference_service] selected RISK provider={_RISK_PROVIDER.name} model={_RISK_PROVIDER.model}")
    return _RISK_PROVIDER


def get_depth_provider() -> DepthProvider:
    global _DEPTH_PROVIDER  # noqa: PLW0603
    if _DEPTH_PROVIDER is None:
        _DEPTH_PROVIDER = _select_depth_provider()
        print(f"[inference_service] selected DEPTH provider={_DEPTH_PROVIDER.name} model={_DEPTH_PROVIDER.model}")
    return _DEPTH_PROVIDER


@app.on_event("startup")
def _startup_provider() -> None:
    get_depth_provider()
    get_ocr_provider()
    get_risk_provider()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    ocr_provider = get_ocr_provider()
    risk_provider = get_risk_provider()
    depth_provider = get_depth_provider()
    return {
        "ok": True,
        "ocrProvider": ocr_provider.name,
        "ocrModel": ocr_provider.model,
        "riskProvider": risk_provider.name,
        "riskModel": risk_provider.model,
        "depthProvider": depth_provider.name,
        "depthModel": depth_provider.model,
    }


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
    image = _decode_pil_image(request.image_b64)
    fail_prob = float(os.getenv("BYES_SERVICE_RISK_FAIL_PROB", os.getenv("BYES_REF_RISK_FAIL_PROB", "0")) or "0")
    if random.random() < max(0.0, min(1.0, fail_prob)):
        raise HTTPException(status_code=503, detail="risk_unavailable")

    delay_ms = max(0, int(os.getenv("BYES_SERVICE_RISK_DELAY_MS", os.getenv("BYES_REF_RISK_DELAY_MS", "0")) or "0"))
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    provider = get_risk_provider()
    try:
        result = provider.infer(image, request.frameSeq)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"risk_infer_failed:{exc.__class__.__name__}") from exc

    model = str(result.get("model", provider.model)).strip() or provider.model
    hazards_raw = result.get("hazards", [])
    hazards: list[dict[str, Any]] = []
    if isinstance(hazards_raw, list):
        for item in hazards_raw:
            if not isinstance(item, dict):
                continue
            hazard_kind = str(item.get("hazardKind", "unknown")).strip() or "unknown"
            severity = str(item.get("severity", "warning")).strip().lower()
            if severity not in {"critical", "warning", "info"}:
                severity = "warning"
            normalized = {"hazardKind": hazard_kind, "severity": severity}
            if "score" in item:
                try:
                    normalized["score"] = float(item["score"])
                except Exception:  # noqa: BLE001
                    pass
            if isinstance(item.get("evidence"), dict):
                normalized["evidence"] = dict(item["evidence"])
            hazards.append(normalized)
    latency_ms = max(0, _now_ms() - started)
    response = {"hazards": hazards, "latencyMs": latency_ms, "model": model}
    if _env_bool("BYES_SERVICE_RISK_DEBUG", False):
        debug_payload = result.get("debug")
        if isinstance(debug_payload, dict):
            response["debug"] = debug_payload
    return response


# TODO: replace infer_ocr and infer_risk internals with real model pipelines:
# - OCR: PaddleOCR/Tesseract tokenizer + postprocess
# - Risk: depth model + hazard projection and thresholding


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}
