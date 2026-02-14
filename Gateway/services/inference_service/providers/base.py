from __future__ import annotations

from typing import Any, Protocol

from PIL import Image


class OCRProvider(Protocol):
    name: str
    model: str

    def infer(self, image: Image.Image, frame_seq: int | None) -> dict[str, Any]:
        ...


class RiskProvider(Protocol):
    name: str
    model: str

    def infer(self, image: Image.Image, frame_seq: int | None) -> dict[str, Any]:
        ...


class SegProvider(Protocol):
    name: str
    model: str
    endpoint: str | None

    def infer(self, image: Image.Image, frame_seq: int | None) -> dict[str, Any]:
        ...
