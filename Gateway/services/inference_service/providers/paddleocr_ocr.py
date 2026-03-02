from __future__ import annotations

import os
from typing import Any

from PIL import Image

from services.inference_service.providers.utils import postprocess_text


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _normalize_polygon(raw: Any) -> list[list[float]] | None:
    if not isinstance(raw, (list, tuple)):
        return None
    points: list[list[float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None
        x = _to_float(item[0])
        y = _to_float(item[1])
        if x is None or y is None:
            return None
        points.append([x, y])
    return points if points else None


def _bbox_from_polygon(poly: list[list[float]] | None) -> list[float] | None:
    if not poly:
        return None
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    if not xs or not ys:
        return None
    return [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))]


class PaddleOcrProvider:
    name = "paddleocr"

    def __init__(self) -> None:
        override = str(os.getenv("BYES_SERVICE_OCR_MODEL_ID", "")).strip()
        self.model = override or "paddleocr"
        self.endpoint: str | None = None
        self._engine: Any | None = None

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "paddleocr_not_installed: install optional OCR deps with "
                "pip install -r Gateway/services/inference_service/requirements-paddleocr.txt"
            ) from exc

        lang = str(
            os.getenv(
                "BYES_SERVICE_OCR_LANG",
                os.getenv("BYES_PADDLEOCR_LANG", "ch"),
            )
        ).strip() or "ch"
        use_gpu = str(os.getenv("BYES_SERVICE_OCR_USE_GPU", "0")).strip().lower() in {"1", "true", "yes", "on"}
        use_angle_cls = str(os.getenv("BYES_PADDLEOCR_ANGLE", "0")).strip().lower() in {"1", "true", "yes", "on"}
        self._engine = PaddleOCR(use_angle_cls=use_angle_cls, lang=lang, use_gpu=use_gpu)
        return self._engine

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del frame_seq, run_id, targets
        engine = self._get_engine()
        result = engine.ocr(image, cls=False)
        lines: list[dict[str, Any]] = []
        for row in result if isinstance(result, list) else []:
            if not isinstance(row, list):
                continue
            for item in row:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                poly = _normalize_polygon(item[0])
                content = item[1]
                text = ""
                score = None
                if isinstance(content, (list, tuple)):
                    if len(content) >= 1:
                        text = str(content[0] or "").strip()
                    if len(content) >= 2:
                        score = _to_float(content[1])
                else:
                    text = str(content or "").strip()
                if not text:
                    continue
                normalized: dict[str, Any] = {"text": postprocess_text(text)}
                if score is not None:
                    normalized["score"] = max(0.0, min(1.0, float(score)))
                bbox = _bbox_from_polygon(poly)
                if bbox is not None:
                    normalized["bbox"] = bbox
                if poly is not None:
                    normalized["box"] = poly
                lines.append(normalized)

        merged_text = postprocess_text(" ".join(str(item.get("text", "")).strip() for item in lines))
        verbose = bool(isinstance(prompt, dict) and prompt.get("verbose"))
        payload: dict[str, Any] = {
            "schemaVersion": "byes.ocr.v1",
            "text": merged_text,
            "lines": lines,
            "linesCount": len(lines),
            "backend": self.name,
            "model": self.model,
            "endpoint": self.endpoint,
            "lang": str(
                os.getenv(
                    "BYES_SERVICE_OCR_LANG",
                    os.getenv("BYES_PADDLEOCR_LANG", "ch"),
                )
            ).strip()
            or "ch",
            "useGpu": str(os.getenv("BYES_SERVICE_OCR_USE_GPU", "0")).strip().lower() in {"1", "true", "yes", "on"},
            "warningsCount": 0,
        }
        if verbose:
            payload["boxes"] = [row.get("box") for row in lines if isinstance(row.get("box"), list)]
            payload["boxesCount"] = len(payload["boxes"])
        return payload
