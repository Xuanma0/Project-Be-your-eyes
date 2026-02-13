from __future__ import annotations

import os
from typing import Any

from PIL import Image

from services.inference_service.providers.utils import postprocess_text


class TesseractOcrProvider:
    name = "tesseract"

    def __init__(self) -> None:
        override = str(os.getenv("BYES_SERVICE_OCR_MODEL_ID", "")).strip()
        self.model = override or "tesseract"

    def infer(self, image: Image.Image, frame_seq: int | None) -> dict[str, Any]:
        del frame_seq
        try:
            import pytesseract  # type: ignore
        except Exception as exc:  # noqa: BLE001
            if _soft_fail_enabled():
                fallback = str(os.getenv("BYES_TESSERACT_FALLBACK_TEXT", "TESSERACT_UNAVAILABLE")).strip()
                return {"text": postprocess_text(fallback), "model": self.model}
            raise RuntimeError(f"pytesseract_import_failed:{exc.__class__.__name__}") from exc

        custom_cmd = str(os.getenv("BYES_TESSERACT_CMD", "")).strip()
        if custom_cmd:
            pytesseract.pytesseract.tesseract_cmd = custom_cmd

        try:
            raw_text = pytesseract.image_to_string(image)
        except Exception as exc:  # noqa: BLE001
            if _soft_fail_enabled():
                fallback = str(os.getenv("BYES_TESSERACT_FALLBACK_TEXT", "TESSERACT_ERROR")).strip()
                return {"text": postprocess_text(fallback), "model": self.model}
            raise RuntimeError(f"tesseract_infer_failed:{exc.__class__.__name__}") from exc
        return {"text": postprocess_text(raw_text), "model": self.model}


def _soft_fail_enabled() -> bool:
    return str(os.getenv("BYES_TESSERACT_SOFT_FAIL", "0")).strip().lower() in {"1", "true", "yes", "on"}
