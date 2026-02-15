from __future__ import annotations

from byes.inference.backends.base import (
    OCRBackend,
    OCRResult,
    RiskBackend,
    RiskResult,
    SegBackend,
    SegResult,
    DepthBackend,
    DepthResult,
)
from byes.inference.backends.http import HttpOCRBackend, HttpRiskBackend, HttpSegBackend, HttpDepthBackend
from byes.inference.backends.mock import MockOCRBackend, MockRiskBackend, MockSegBackend, MockDepthBackend

__all__ = [
    "OCRBackend",
    "OCRResult",
    "RiskBackend",
    "RiskResult",
    "SegBackend",
    "SegResult",
    "DepthBackend",
    "DepthResult",
    "HttpOCRBackend",
    "HttpRiskBackend",
    "HttpSegBackend",
    "HttpDepthBackend",
    "MockOCRBackend",
    "MockRiskBackend",
    "MockSegBackend",
    "MockDepthBackend",
]
