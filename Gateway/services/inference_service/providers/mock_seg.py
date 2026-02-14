from __future__ import annotations

from typing import Any

from PIL import Image


class MockSegProvider:
    name = "mock"

    def __init__(self, model_id: str | None = None) -> None:
        self.model = str(model_id or "").strip() or "mock-seg"
        self.endpoint: str | None = None

    def infer(self, image: Image.Image, frame_seq: int | None) -> dict[str, Any]:
        del image, frame_seq
        return {"segments": [], "model": self.model}
