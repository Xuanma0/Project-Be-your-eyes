from __future__ import annotations

from services.inference_service.providers.base import OCRProvider, RiskProvider
from services.inference_service.providers.heuristic_risk import HeuristicRiskProvider
from services.inference_service.providers.paddleocr_ocr import PaddleOcrProvider
from services.inference_service.providers.reference_ocr import ReferenceOcrProvider
from services.inference_service.providers.reference_risk import ReferenceRiskProvider
from services.inference_service.providers.tesseract_ocr import TesseractOcrProvider

__all__ = [
    "OCRProvider",
    "RiskProvider",
    "ReferenceOcrProvider",
    "TesseractOcrProvider",
    "PaddleOcrProvider",
    "ReferenceRiskProvider",
    "HeuristicRiskProvider",
]
