from __future__ import annotations

from typing import Any, Protocol, TypedDict

from PIL import Image


class DepthMap(TypedDict, total=False):
    depth: list[list[float]]
    min: float
    max: float
    scale: str
    width: int
    height: int
    model: str
    debug: dict[str, Any]


class DepthProvider(Protocol):
    name: str
    model: str

    def infer_depth(self, image: Image.Image, frame_seq: int | None = None) -> DepthMap | None:
        ...
