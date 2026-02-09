from __future__ import annotations

from byes.inference.backends.base import OCRBackend, OCRResult, RiskBackend, RiskResult
from byes.inference.backends.http import HttpOCRBackend, HttpRiskBackend
from byes.inference.backends.mock import MockOCRBackend, MockRiskBackend

__all__ = [
    "OCRBackend",
    "OCRResult",
    "RiskBackend",
    "RiskResult",
    "HttpOCRBackend",
    "HttpRiskBackend",
    "MockOCRBackend",
    "MockRiskBackend",
]
