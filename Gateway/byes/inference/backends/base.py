from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class OCRResult:
    text: str = ""
    latency_ms: int | None = None
    status: str = "ok"
    error: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RiskResult:
    hazards: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int | None = None
    status: str = "ok"
    error: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class OCRBackend(Protocol):
    name: str
    model_id: str | None
    endpoint: str | None

    async def infer(self, image_bytes: bytes, frame_seq: int | None, ts_ms: int) -> OCRResult:
        ...


class RiskBackend(Protocol):
    name: str
    model_id: str | None
    endpoint: str | None

    async def infer(self, image_bytes: bytes, frame_seq: int | None, ts_ms: int) -> RiskResult:
        ...
