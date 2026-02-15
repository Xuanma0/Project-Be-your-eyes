from __future__ import annotations

import os

from byes.config import GatewayConfig
from byes.inference.backends.base import OCRBackend, RiskBackend, SegBackend, DepthBackend
from byes.inference.backends.http import HttpOCRBackend, HttpRiskBackend, HttpSegBackend, HttpDepthBackend
from byes.inference.backends.mock import MockOCRBackend, MockRiskBackend, MockSegBackend, MockDepthBackend


def _backend_name(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"http", "mock"}:
        return normalized
    return "mock"


def get_ocr_backend(config: GatewayConfig) -> OCRBackend:
    name = _backend_name(os.getenv("BYES_OCR_BACKEND", config.inference_ocr_backend))
    model_id = str(os.getenv("BYES_OCR_MODEL_ID", config.inference_ocr_model_id)).strip() or None
    if name == "http":
        url = os.getenv("BYES_OCR_HTTP_URL", config.inference_ocr_http_url)
        timeout_ms = int(os.getenv("BYES_OCR_HTTP_TIMEOUT_MS", str(config.inference_ocr_timeout_ms)) or config.inference_ocr_timeout_ms)
        return HttpOCRBackend(url=url, timeout_ms=timeout_ms, model_id=model_id)
    return MockOCRBackend(text=os.getenv("BYES_MOCK_INFER_OCR_TEXT", "EXIT"), model_id=model_id or "mock-ocr")


def get_risk_backend(config: GatewayConfig) -> RiskBackend:
    name = _backend_name(os.getenv("BYES_RISK_BACKEND", config.inference_risk_backend))
    model_id = str(os.getenv("BYES_RISK_MODEL_ID", config.inference_risk_model_id)).strip() or None
    if name == "http":
        url = os.getenv("BYES_RISK_HTTP_URL", config.inference_risk_http_url)
        timeout_ms = int(
            os.getenv("BYES_RISK_HTTP_TIMEOUT_MS", str(config.inference_risk_timeout_ms)) or config.inference_risk_timeout_ms
        )
        return HttpRiskBackend(url=url, timeout_ms=timeout_ms, model_id=model_id)
    return MockRiskBackend(model_id=model_id or "mock-risk")


def get_seg_backend(config: GatewayConfig) -> SegBackend:
    name = _backend_name(os.getenv("BYES_SEG_BACKEND", config.inference_seg_backend))
    model_id = str(os.getenv("BYES_SEG_MODEL_ID", config.inference_seg_model_id)).strip() or None
    if name == "http":
        url = os.getenv("BYES_SEG_HTTP_URL", config.inference_seg_http_url)
        timeout_ms = int(os.getenv("BYES_SEG_HTTP_TIMEOUT_MS", str(config.inference_seg_timeout_ms)) or config.inference_seg_timeout_ms)
        return HttpSegBackend(url=url, timeout_ms=timeout_ms, model_id=model_id)
    return MockSegBackend(model_id=model_id or "mock-seg")


def get_depth_backend(config: GatewayConfig) -> DepthBackend:
    name = _backend_name(os.getenv("BYES_DEPTH_BACKEND", config.inference_depth_backend))
    model_id = str(os.getenv("BYES_DEPTH_MODEL_ID", config.inference_depth_model_id)).strip() or None
    if name == "http":
        url = os.getenv("BYES_DEPTH_HTTP_URL", config.inference_depth_http_url)
        timeout_ms = int(
            os.getenv("BYES_DEPTH_HTTP_TIMEOUT_MS", str(config.inference_depth_timeout_ms)) or config.inference_depth_timeout_ms
        )
        return HttpDepthBackend(url=url, timeout_ms=timeout_ms, model_id=model_id)
    return MockDepthBackend(model_id=model_id or "mock-depth")
