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
    SlamBackend,
    SlamResult,
)
from byes.inference.backends.http import HttpOCRBackend, HttpRiskBackend, HttpSegBackend, HttpDepthBackend, HttpSlamBackend
from byes.inference.backends.mock import MockOCRBackend, MockRiskBackend, MockSegBackend, MockDepthBackend, MockSlamBackend

__all__ = [
    "OCRBackend",
    "OCRResult",
    "RiskBackend",
    "RiskResult",
    "SegBackend",
    "SegResult",
    "DepthBackend",
    "DepthResult",
    "SlamBackend",
    "SlamResult",
    "HttpOCRBackend",
    "HttpRiskBackend",
    "HttpSegBackend",
    "HttpDepthBackend",
    "HttpSlamBackend",
    "MockOCRBackend",
    "MockRiskBackend",
    "MockSegBackend",
    "MockDepthBackend",
    "MockSlamBackend",
]
