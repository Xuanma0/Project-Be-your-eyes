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

from services.inference_service.providers.base import OCRProvider, RiskProvider, SegProvider
from services.inference_service.providers import create_seg_provider
from services.inference_service.providers.depth_base import DepthProvider
from services.inference_service.providers.depth_none import NoneDepthProvider
from services.inference_service.providers.depth_synth import SynthDepthProvider
from services.inference_service.providers.onnx_depth import OnnxDepthProvider
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
    riskThresholds: dict[str, float] | None = None


app = FastAPI(title="BYES Reference Inference Service")
_OCR_PROVIDER: OCRProvider | None = None
_RISK_PROVIDER: RiskProvider | None = None
_DEPTH_PROVIDER: DepthProvider | None = None
_SEG_PROVIDER: SegProvider | None = None


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
    if name == "onnx":
        return OnnxDepthProvider()
    if name == "midas":
        try:
            from services.inference_service.providers.depth_midas import MidasOnnxDepthProvider
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"depth_provider_import_failed:{exc.__class__.__name__}") from exc
        return MidasOnnxDepthProvider()
    return NoneDepthProvider()


def _select_seg_provider() -> SegProvider:
    name = str(os.getenv("BYES_SERVICE_SEG_PROVIDER", "mock")).strip().lower()
    return create_seg_provider(name=name)


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


def get_seg_provider() -> SegProvider:
    global _SEG_PROVIDER  # noqa: PLW0603
    if _SEG_PROVIDER is None:
        _SEG_PROVIDER = _select_seg_provider()
        print(f"[inference_service] selected SEG provider={_SEG_PROVIDER.name} model={_SEG_PROVIDER.model}")
    return _SEG_PROVIDER


@app.on_event("startup")
def _startup_provider() -> None:
    get_depth_provider()
    get_ocr_provider()
    get_risk_provider()
    get_seg_provider()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    ocr_provider = get_ocr_provider()
    risk_provider = get_risk_provider()
    depth_provider = get_depth_provider()
    seg_provider = get_seg_provider()
    return {
        "ok": True,
        "ocrProvider": ocr_provider.name,
        "ocrModel": ocr_provider.model,
        "riskProvider": risk_provider.name,
        "riskModel": risk_provider.model,
        "depthProvider": depth_provider.name,
        "depthModel": depth_provider.model,
        "segProvider": seg_provider.name,
        "segModel": seg_provider.model,
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
    request_started = time.perf_counter()
    decode_started = time.perf_counter()
    image = _decode_pil_image(request.image_b64)
    decode_ms = (time.perf_counter() - decode_started) * 1000.0
    fail_prob = float(os.getenv("BYES_SERVICE_RISK_FAIL_PROB", os.getenv("BYES_REF_RISK_FAIL_PROB", "0")) or "0")
    if random.random() < max(0.0, min(1.0, fail_prob)):
        raise HTTPException(status_code=503, detail="risk_unavailable")

    delay_ms = max(0, int(os.getenv("BYES_SERVICE_RISK_DELAY_MS", os.getenv("BYES_REF_RISK_DELAY_MS", "0")) or "0"))
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    provider = get_risk_provider()
    risk_thresholds_override: dict[str, float] | None = None
    if isinstance(request.riskThresholds, dict):
        risk_thresholds_override = {}
        for key, value in request.riskThresholds.items():
            try:
                risk_thresholds_override[str(key)] = float(value)
            except Exception:  # noqa: BLE001
                continue
    try:
        if risk_thresholds_override:
            try:
                result = provider.infer(image, request.frameSeq, thresholds_override=risk_thresholds_override)
            except TypeError:
                result = provider.infer(image, request.frameSeq)
        else:
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
        merged_debug = dict(debug_payload) if isinstance(debug_payload, dict) else {}
        timings = merged_debug.get("timings")
        timings_payload = dict(timings) if isinstance(timings, dict) else {}
        timings_payload["decodeMs"] = round(max(0.0, decode_ms), 3)
        timings_payload["totalMs"] = round(max(0.0, (time.perf_counter() - request_started) * 1000.0), 3)
        merged_debug["timings"] = timings_payload
        response["debug"] = merged_debug
    return response


@app.post("/seg")
def infer_seg(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    image = _decode_pil_image(request.image_b64)
    provider = get_seg_provider()
    try:
        result = provider.infer(image, request.frameSeq)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"seg_infer_failed:{exc.__class__.__name__}") from exc

    segments_raw = result.get("segments")
    segments_raw = segments_raw if isinstance(segments_raw, list) else []
    segments: list[dict[str, Any]] = []
    for item in segments_raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip() or "unknown"
        try:
            score = float(item.get("score", 0.0))
        except Exception:  # noqa: BLE001
            score = 0.0
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        normalized_bbox: list[float] = []
        try:
            normalized_bbox = [float(value) for value in bbox]
        except Exception:  # noqa: BLE001
            continue
        segments.append({"label": label, "score": score, "bbox": normalized_bbox})

    model = str(result.get("model", provider.model)).strip() or provider.model
    latency_ms = max(0, _now_ms() - started)
    return {"segments": segments, "latencyMs": latency_ms, "model": model}


# TODO: replace infer_ocr and infer_risk internals with real model pipelines:
# - OCR: PaddleOCR/Tesseract tokenizer + postprocess
# - Risk: depth model + hazard projection and thresholding


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}
