from __future__ import annotations

import os
from typing import Any

from PIL import Image

from services.inference_service.providers.utils import postprocess_text


class ReferenceOcrProvider:
    name = "reference"

    def __init__(self) -> None:
        default_model = str(os.getenv("BYES_REF_OCR_MODEL_ID", "reference-ocr-v1")).strip() or "reference-ocr-v1"
        override = str(os.getenv("BYES_SERVICE_OCR_MODEL_ID", "")).strip()
        self.model = override or default_model

    def infer(self, image: Image.Image, frame_seq: int | None) -> dict[str, Any]:
        del image
        text = str(os.getenv("BYES_REF_OCR_TEXT", "EXIT")).strip() or "EXIT"
        if isinstance(frame_seq, int) and frame_seq % 2 == 0:
            text = str(os.getenv("BYES_REF_OCR_TEXT_ALT", text)).strip() or text
        return {"text": postprocess_text(text), "model": self.model}

