from __future__ import annotations

import os

from byes.config import GatewayConfig
from byes.inference.backends.base import OCRBackend, RiskBackend
from byes.inference.backends.http import HttpOCRBackend, HttpRiskBackend
from byes.inference.backends.mock import MockOCRBackend, MockRiskBackend


def _backend_name(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"http", "mock"}:
        return normalized
    return "mock"


def get_ocr_backend(config: GatewayConfig) -> OCRBackend:
    name = _backend_name(os.getenv("BYES_OCR_BACKEND", config.inference_ocr_backend))
    if name == "http":
        url = os.getenv("BYES_OCR_HTTP_URL", config.inference_ocr_http_url)
        timeout_ms = int(os.getenv("BYES_OCR_HTTP_TIMEOUT_MS", str(config.inference_ocr_timeout_ms)) or config.inference_ocr_timeout_ms)
        return HttpOCRBackend(url=url, timeout_ms=timeout_ms)
    return MockOCRBackend(text=os.getenv("BYES_MOCK_INFER_OCR_TEXT", "EXIT"))


def get_risk_backend(config: GatewayConfig) -> RiskBackend:
    name = _backend_name(os.getenv("BYES_RISK_BACKEND", config.inference_risk_backend))
    if name == "http":
        url = os.getenv("BYES_RISK_HTTP_URL", config.inference_risk_http_url)
        timeout_ms = int(
            os.getenv("BYES_RISK_HTTP_TIMEOUT_MS", str(config.inference_risk_timeout_ms)) or config.inference_risk_timeout_ms
        )
        return HttpRiskBackend(url=url, timeout_ms=timeout_ms)
    return MockRiskBackend()
