from __future__ import annotations

from typing import Any

from PIL import Image


class MockDetProvider:
    name = "mock"

    def __init__(self, model_id: str | None = None) -> None:
        self.model = str(model_id or "").strip() or "mock-det"
        self.endpoint: str | None = None

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del frame_seq, run_id, targets, prompt
        width, height = image.size
        box = [max(0.0, width * 0.15), max(0.0, height * 0.2), max(1.0, width * 0.7), max(1.0, height * 0.85)]
        return {
            "schemaVersion": "byes.det.v1",
            "objects": [
                {
                    "label": "person",
                    "conf": 0.82,
                    "box_xyxy": box,
                    "box_norm": [
                        box[0] / max(1.0, float(width)),
                        box[1] / max(1.0, float(height)),
                        box[2] / max(1.0, float(width)),
                        box[3] / max(1.0, float(height)),
                    ],
                }
            ],
            "objectsCount": 1,
            "topK": 5,
            "imageWidth": int(width),
            "imageHeight": int(height),
            "backend": self.name,
            "model": self.model,
            "endpoint": self.endpoint,
        }
