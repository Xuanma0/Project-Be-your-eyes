from __future__ import annotations

import time
from typing import Any

from byes.inference.backends.base import OCRResult, RiskResult


def _now_ms() -> int:
    return int(time.time() * 1000)


class MockOCRBackend:
    name = "mock"

    def __init__(self, text: str = "EXIT", confidence: float = 0.9, model_id: str = "mock-ocr") -> None:
        self._text = str(text)
        self._confidence = float(confidence)
        self.model_id: str | None = str(model_id or "").strip() or "mock-ocr"
        self.endpoint: str | None = None

    async def infer(self, image_bytes: bytes, frame_seq: int | None, ts_ms: int) -> OCRResult:
        started = _now_ms()
        del image_bytes, frame_seq, ts_ms
        latency = max(0, _now_ms() - started)
        return OCRResult(
            text=self._text,
            latency_ms=latency,
            status="ok",
            payload={
                "text": self._text,
                "confidence": self._confidence,
                "backend": "mock",
            },
        )


class MockRiskBackend:
    name = "mock"

    def __init__(self, hazards: list[dict[str, Any]] | None = None, model_id: str = "mock-risk") -> None:
        self._hazards = list(hazards) if hazards is not None else [
            {"hazardKind": "stair_down", "severity": "warning"},
        ]
        self.model_id: str | None = str(model_id or "").strip() or "mock-risk"
        self.endpoint: str | None = None

    async def infer(self, image_bytes: bytes, frame_seq: int | None, ts_ms: int) -> RiskResult:
        started = _now_ms()
        del image_bytes, frame_seq, ts_ms
        latency = max(0, _now_ms() - started)
        return RiskResult(
            hazards=list(self._hazards),
            latency_ms=latency,
            status="ok",
            payload={
                "hazards": list(self._hazards),
                "backend": "mock",
            },
        )
