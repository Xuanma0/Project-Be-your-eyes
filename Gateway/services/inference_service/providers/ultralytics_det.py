from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        return float(raw)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        return int(raw)
    except Exception:
        return int(default)


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _split_prompt_csv(text: str) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for token in str(text or "").split(","):
        value = token.strip()
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        labels.append(value)
    return labels


def _normalize_polygon(raw: Any, *, max_points: int = 128) -> list[list[float]] | None:
    if raw is None:
        return None
    rows = raw.tolist() if hasattr(raw, "tolist") else raw
    if not isinstance(rows, list):
        return None
    out: list[list[float]] = []
    for item in rows:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            x = float(item[0])
            y = float(item[1])
        except Exception:
            continue
        out.append([x, y])
        if len(out) >= max_points:
            break
    return out if out else None


class UltralyticsDetProvider:
    name = "ultralytics"

    def __init__(self) -> None:
        model_path_env = str(os.getenv("BYES_SERVICE_DET_MODEL_PATH", "")).strip()
        model_env = str(os.getenv("BYES_SERVICE_DET_MODEL", "")).strip()
        model_id_env = str(os.getenv("BYES_SERVICE_DET_MODEL_ID", "")).strip()
        self.model = model_path_env or model_env or model_id_env or "yolo26"
        self.endpoint: str | None = None
        self.conf = _clamp_float(_env_float("BYES_SERVICE_DET_CONF", 0.25), 0.01, 0.99)
        self.imgsz = max(64, _env_int("BYES_SERVICE_DET_IMGSZ", 640))
        self.top_k = max(1, _env_int("BYES_SERVICE_DET_TOP_K", 5))
        self.device = str(os.getenv("BYES_SERVICE_DET_DEVICE", "")).strip() or None
        self.open_vocab_enabled = _env_bool("BYES_SERVICE_DET_OPENVOCAB", False)
        self.prompt_default = str(os.getenv("BYES_SERVICE_DET_PROMPT_DEFAULT", "")).strip()
        self.include_masks = _env_bool("BYES_SERVICE_DET_INCLUDE_MASK", True)
        self._engine: Any | None = None

    def _resolve_model_ref(self) -> str:
        token = str(self.model).strip()
        if not token:
            raise RuntimeError("BYES_SERVICE_DET_MODEL is empty")
        looks_like_path = any(sep in token for sep in ("/", "\\")) or token.lower().endswith(".pt")
        if not looks_like_path:
            return token
        path = Path(token).expanduser()
        if not path.exists() or not path.is_file():
            raise RuntimeError(
                f"det_model_not_found:{path}; set BYES_SERVICE_DET_MODEL to an existing model path "
                "or an Ultralytics model id (for example yolo11n.pt)"
            )
        return str(path)

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "ultralytics_not_installed: install optional DET deps with "
                "pip install -r Gateway/services/inference_service/requirements-ultralytics.txt"
            ) from exc
        model_ref = self._resolve_model_ref()
        self._engine = YOLO(model_ref)
        return self._engine

    def _extract_prompt_labels(self, prompt: dict[str, Any] | None) -> list[str]:
        if not isinstance(prompt, dict):
            return _split_prompt_csv(self.prompt_default)
        labels_raw = prompt.get("labels", prompt.get("classes", prompt.get("names")))
        if isinstance(labels_raw, list):
            out: list[str] = []
            seen: set[str] = set()
            for item in labels_raw:
                token = str(item or "").strip()
                key = token.lower()
                if not token or key in seen:
                    continue
                seen.add(key)
                out.append(token)
            if out:
                return out
        text = str(prompt.get("text", prompt.get("prompt", ""))).strip()
        if text:
            return _split_prompt_csv(text)
        return _split_prompt_csv(self.prompt_default)

    @staticmethod
    def _apply_open_vocab_classes(engine: Any, labels: list[str]) -> str | None:
        if not labels:
            return None
        holders = [engine, getattr(engine, "model", None)]
        for holder in holders:
            if holder is None:
                continue
            setter = getattr(holder, "set_classes", None)
            if callable(setter):
                try:
                    setter(labels)
                    return None
                except Exception as exc:  # noqa: BLE001
                    return f"openvocab_set_classes_failed:{exc.__class__.__name__}"
        return "openvocab_set_classes_unavailable"

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
        width, height = image.size
        prompt_labels = self._extract_prompt_labels(prompt)
        open_vocab = bool(self.open_vocab_enabled or prompt_labels)
        warnings: list[str] = []
        if open_vocab:
            warning = self._apply_open_vocab_classes(engine, prompt_labels)
            if warning:
                warnings.append(warning)

        kwargs: dict[str, Any] = {
            "conf": float(self.conf),
            "imgsz": int(self.imgsz),
            "verbose": False,
        }
        if self.device:
            kwargs["device"] = self.device
        predictions = engine.predict(image, **kwargs)
        if not predictions:
            return {
                "schemaVersion": "byes.det.v1",
                "objects": [],
                "objectsCount": 0,
                "topK": self.top_k,
                "imageWidth": int(width),
                "imageHeight": int(height),
                "backend": self.name,
                "model": self.model,
                "endpoint": self.endpoint,
            }

        pred = predictions[0]
        boxes = getattr(pred, "boxes", None)
        names = getattr(pred, "names", {}) or {}
        mask_polygons: list[list[list[float]] | None] = []
        if self.include_masks:
            masks = getattr(pred, "masks", None)
            masks_xy = getattr(masks, "xy", None) if masks is not None else None
            if isinstance(masks_xy, list):
                for polygon in masks_xy:
                    mask_polygons.append(_normalize_polygon(polygon))
        objects: list[dict[str, Any]] = []

        if boxes is not None:
            try:
                xyxy_rows = boxes.xyxy.tolist()  # type: ignore[attr-defined]
            except Exception:
                xyxy_rows = []
            try:
                conf_rows = boxes.conf.tolist()  # type: ignore[attr-defined]
            except Exception:
                conf_rows = [0.0] * len(xyxy_rows)
            try:
                cls_rows = boxes.cls.tolist()  # type: ignore[attr-defined]
            except Exception:
                cls_rows = [-1] * len(xyxy_rows)

            for idx, row in enumerate(xyxy_rows):
                if not isinstance(row, (list, tuple)) or len(row) != 4:
                    continue
                try:
                    x0, y0, x1, y1 = [float(v) for v in row]
                except Exception:
                    continue
                conf = 0.0
                if idx < len(conf_rows):
                    try:
                        conf = float(conf_rows[idx])
                    except Exception:
                        conf = 0.0
                cls_id = -1
                if idx < len(cls_rows):
                    try:
                        cls_id = int(cls_rows[idx])
                    except Exception:
                        cls_id = -1
                label = str(names.get(cls_id, f"class_{cls_id}")).strip() if isinstance(names, dict) else f"class_{cls_id}"
                normalized = [
                    _clamp_float(x0 / max(1.0, float(width)), 0.0, 1.0),
                    _clamp_float(y0 / max(1.0, float(height)), 0.0, 1.0),
                    _clamp_float(x1 / max(1.0, float(width)), 0.0, 1.0),
                    _clamp_float(y1 / max(1.0, float(height)), 0.0, 1.0),
                ]
                objects.append(
                    {
                        "label": label or "unknown",
                        "conf": _clamp_float(conf, 0.0, 1.0),
                        "box_xyxy": [x0, y0, x1, y1],
                        "box_norm": normalized,
                    }
                )

        objects.sort(key=lambda row: float(row.get("conf", 0.0)), reverse=True)
        if len(objects) > self.top_k:
            objects = objects[: self.top_k]
        if mask_polygons:
            for idx, row in enumerate(objects):
                if idx >= len(mask_polygons):
                    break
                poly = mask_polygons[idx]
                if not poly:
                    continue
                norm_points: list[list[float]] = []
                for point in poly:
                    norm_points.append(
                        [
                            _clamp_float(point[0] / max(1.0, float(width)), 0.0, 1.0),
                            _clamp_float(point[1] / max(1.0, float(height)), 0.0, 1.0),
                        ]
                    )
                row["mask"] = {
                    "format": "polygon_v1",
                    "points": poly,
                    "pointsNorm": norm_points,
                }

        return {
            "schemaVersion": "byes.det.v1",
            "objects": objects,
            "objectsCount": len(objects),
            "topK": self.top_k,
            "imageWidth": int(width),
            "imageHeight": int(height),
            "backend": self.name,
            "model": self.model,
            "endpoint": self.endpoint,
            "openVocab": bool(open_vocab),
            "promptUsed": prompt_labels if prompt_labels else None,
            "warningsCount": len(warnings),
            "warnings": warnings or None,
        }
