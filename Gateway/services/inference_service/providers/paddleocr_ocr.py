from __future__ import annotations

import os
from typing import Any

from PIL import Image

from services.inference_service.providers.utils import postprocess_text


class PaddleOcrProvider:
    name = "paddleocr"

    def __init__(self) -> None:
        override = str(os.getenv("BYES_SERVICE_OCR_MODEL_ID", "")).strip()
        self.model = override or "paddleocr"
        self._engine: Any | None = None

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"paddleocr_import_failed:{exc.__class__.__name__}") from exc
        lang = str(os.getenv("BYES_PADDLEOCR_LANG", "en")).strip() or "en"
        use_angle_cls = str(os.getenv("BYES_PADDLEOCR_ANGLE", "0")).strip().lower() in {"1", "true", "yes", "on"}
        self._engine = PaddleOCR(use_angle_cls=use_angle_cls, lang=lang)
        return self._engine

    def infer(self, image: Image.Image, frame_seq: int | None) -> dict[str, Any]:
        del frame_seq
        engine = self._get_engine()
        result = engine.ocr(image, cls=False)
        texts: list[str] = []
        if isinstance(result, list):
            for row in result:
                if not isinstance(row, list):
                    continue
                for item in row:
                    if not isinstance(item, list) and not isinstance(item, tuple):
                        continue
                    if len(item) < 2:
                        continue
                    content = item[1]
                    if isinstance(content, (list, tuple)) and len(content) >= 1:
                        text = str(content[0] or "").strip()
                        if text:
                            texts.append(text)
        joined = " ".join(texts)
        return {"text": postprocess_text(joined), "model": self.model}

