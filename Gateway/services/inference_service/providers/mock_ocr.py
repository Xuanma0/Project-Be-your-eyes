from __future__ import annotations

from typing import Any

from PIL import Image


class MockOcrProvider:
    name = "mock"

    def __init__(self, model_id: str | None = None) -> None:
        self.model = str(model_id or "").strip() or "mock-ocr"
        self.endpoint: str | None = None

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del image, frame_seq, run_id, targets, prompt
        return {
            "lines": [{"text": "EXIT", "score": 0.92}],
            "linesCount": 1,
            "model": self.model,
            "backend": self.name,
            "endpoint": self.endpoint,
            "warningsCount": 0,
        }
