from __future__ import annotations

from byes.inference.backends.base import (
    OCRBackend,
    OCRResult,
    RiskBackend,
    RiskResult,
    SegBackend,
    SegResult,
    DetBackend,
    DetResult,
    DepthBackend,
    DepthResult,
    SlamBackend,
    SlamResult,
)
from byes.inference.backends.http import (
    HttpOCRBackend,
    HttpRiskBackend,
    HttpSegBackend,
    HttpDetBackend,
    HttpDepthBackend,
    HttpSlamBackend,
)
from byes.inference.backends.mock import (
    MockOCRBackend,
    MockRiskBackend,
    MockSegBackend,
    MockDetBackend,
    MockDepthBackend,
    MockSlamBackend,
)

__all__ = [
    "OCRBackend",
    "OCRResult",
    "RiskBackend",
    "RiskResult",
    "SegBackend",
    "SegResult",
    "DetBackend",
    "DetResult",
    "DepthBackend",
    "DepthResult",
    "SlamBackend",
    "SlamResult",
    "HttpOCRBackend",
    "HttpRiskBackend",
    "HttpSegBackend",
    "HttpDetBackend",
    "HttpDepthBackend",
    "HttpSlamBackend",
    "MockOCRBackend",
    "MockRiskBackend",
    "MockSegBackend",
    "MockDetBackend",
    "MockDepthBackend",
    "MockSlamBackend",
]
