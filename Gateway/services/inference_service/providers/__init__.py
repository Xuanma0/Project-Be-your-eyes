from __future__ import annotations

import os

from services.inference_service.providers.base import OCRProvider, RiskProvider, SegProvider
from services.inference_service.providers.depth_base import DepthMap, DepthProvider
from services.inference_service.providers.depth_midas import MidasOnnxDepthProvider
from services.inference_service.providers.depth_none import NoneDepthProvider
from services.inference_service.providers.onnx_depth import OnnxDepthProvider
from services.inference_service.providers.depth_synth import SynthDepthProvider
from services.inference_service.providers.http_seg import HttpSegProvider
from services.inference_service.providers.heuristic_risk import HeuristicRiskProvider
from services.inference_service.providers.mock_seg import MockSegProvider
from services.inference_service.providers.paddleocr_ocr import PaddleOcrProvider
from services.inference_service.providers.reference_ocr import ReferenceOcrProvider
from services.inference_service.providers.reference_risk import ReferenceRiskProvider
from services.inference_service.providers.tesseract_ocr import TesseractOcrProvider


def create_seg_provider(name: str | None = None) -> SegProvider:
    provider = str(name or os.getenv("BYES_SERVICE_SEG_PROVIDER", "mock")).strip().lower()
    model_id = str(os.getenv("BYES_SERVICE_SEG_MODEL_ID", "")).strip() or None
    if provider == "http":
        endpoint = str(os.getenv("BYES_SERVICE_SEG_ENDPOINT", "")).strip()
        timeout_ms = int(str(os.getenv("BYES_SERVICE_SEG_TIMEOUT_MS", "1200")).strip() or "1200")
        return HttpSegProvider(endpoint=endpoint, model_id=model_id, timeout_ms=timeout_ms)
    return MockSegProvider(model_id=model_id)


__all__ = [
    "OCRProvider",
    "RiskProvider",
    "SegProvider",
    "DepthProvider",
    "DepthMap",
    "ReferenceOcrProvider",
    "TesseractOcrProvider",
    "PaddleOcrProvider",
    "ReferenceRiskProvider",
    "HeuristicRiskProvider",
    "MockSegProvider",
    "HttpSegProvider",
    "create_seg_provider",
    "NoneDepthProvider",
    "SynthDepthProvider",
    "MidasOnnxDepthProvider",
    "OnnxDepthProvider",
]
