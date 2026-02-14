from __future__ import annotations

from byes.inference.backends.base import OCRBackend, OCRResult, RiskBackend, RiskResult, SegBackend, SegResult
from byes.inference.backends.http import HttpOCRBackend, HttpRiskBackend, HttpSegBackend
from byes.inference.backends.mock import MockOCRBackend, MockRiskBackend, MockSegBackend

__all__ = [
    "OCRBackend",
    "OCRResult",
    "RiskBackend",
    "RiskResult",
    "SegBackend",
    "SegResult",
    "HttpOCRBackend",
    "HttpRiskBackend",
    "HttpSegBackend",
    "MockOCRBackend",
    "MockRiskBackend",
    "MockSegBackend",
]
