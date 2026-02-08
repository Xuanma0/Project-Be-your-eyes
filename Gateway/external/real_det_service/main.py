from __future__ import annotations

import asyncio
import io
import json
import os
import random
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile


def _now_ms() -> int:
    return int(time.time() * 1000)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return str(raw).strip() if raw is not None else default


def _default_labels() -> list[str]:
    return [
        "person",
        "bicycle",
        "car",
        "motorcycle",
        "airplane",
        "bus",
        "train",
        "truck",
        "boat",
        "traffic light",
        "fire hydrant",
        "stop sign",
        "parking meter",
        "bench",
        "bird",
        "cat",
        "dog",
        "horse",
        "sheep",
        "cow",
        "elephant",
        "bear",
        "zebra",
        "giraffe",
        "backpack",
        "umbrella",
        "handbag",
        "tie",
        "suitcase",
        "frisbee",
        "skis",
        "snowboard",
        "sports ball",
        "kite",
        "baseball bat",
        "baseball glove",
        "skateboard",
        "surfboard",
        "tennis racket",
        "bottle",
        "wine glass",
        "cup",
        "fork",
        "knife",
        "spoon",
        "bowl",
        "banana",
        "apple",
        "sandwich",
        "orange",
        "broccoli",
        "carrot",
        "hot dog",
        "pizza",
        "donut",
        "cake",
        "chair",
        "couch",
        "potted plant",
        "bed",
        "dining table",
        "toilet",
        "tv",
        "laptop",
        "mouse",
        "remote",
        "keyboard",
        "cell phone",
        "microwave",
        "oven",
        "toaster",
        "sink",
        "refrigerator",
        "book",
        "clock",
        "vase",
        "scissors",
        "teddy bear",
        "hair drier",
        "toothbrush",
    ]


class OnnxDetRuntime:
    def __init__(
        self,
        model_path: Path,
        *,
        input_size: int,
        conf_threshold: float,
        nms_iou_threshold: float,
        max_det: int,
        labels: list[str],
    ) -> None:
        import numpy as np
        import onnxruntime as ort

        self._np = np
        self._model_path = model_path
        self._conf_threshold = max(0.01, min(1.0, conf_threshold))
        self._nms_iou_threshold = max(0.05, min(0.95, nms_iou_threshold))
        self._max_det = max(1, max_det)
        self._labels = labels or _default_labels()

        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        input_shape = self._session.get_inputs()[0].shape
        input_h = input_shape[2] if len(input_shape) > 2 and isinstance(input_shape[2], int) else input_size
        input_w = input_shape[3] if len(input_shape) > 3 and isinstance(input_shape[3], int) else input_size
        self._input_h = max(32, int(input_h))
        self._input_w = max(32, int(input_w))

    @property
    def input_hw(self) -> tuple[int, int]:
        return self._input_h, self._input_w

    def warmup(self) -> None:
        sample = self._np.zeros((1, 3, self._input_h, self._input_w), dtype=self._np.float32)
        _ = self._session.run(None, {self._input_name: sample})

    def infer(self, image_bytes: bytes) -> list[dict[str, Any]]:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor, scale, pad_x, pad_y, orig_w, orig_h = self._preprocess(image)
        outputs = self._session.run(None, {self._input_name: tensor})
        return self._postprocess(
            outputs=outputs,
            scale=scale,
            pad_x=pad_x,
            pad_y=pad_y,
            orig_w=orig_w,
            orig_h=orig_h,
        )

    def _preprocess(self, image: Any) -> tuple[Any, float, float, float, int, int]:
        np = self._np
        orig_w, orig_h = image.size
        scale = min(self._input_w / max(orig_w, 1), self._input_h / max(orig_h, 1))
        new_w = max(1, int(round(orig_w * scale)))
        new_h = max(1, int(round(orig_h * scale)))
        resized = image.resize((new_w, new_h))

        canvas = np.full((self._input_h, self._input_w, 3), 114, dtype=np.uint8)
        pad_x = float((self._input_w - new_w) // 2)
        pad_y = float((self._input_h - new_h) // 2)
        arr = np.asarray(resized, dtype=np.uint8)
        canvas[int(pad_y) : int(pad_y) + new_h, int(pad_x) : int(pad_x) + new_w] = arr

        tensor = canvas.astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
        return tensor, float(scale), pad_x, pad_y, int(orig_w), int(orig_h)

    def _postprocess(
        self,
        *,
        outputs: list[Any],
        scale: float,
        pad_x: float,
        pad_y: float,
        orig_w: int,
        orig_h: int,
    ) -> list[dict[str, Any]]:
        np = self._np
        matrix = self._select_matrix(outputs)
        if matrix.size == 0:
            return []
        matrix = self._normalize_matrix(matrix)
        if matrix.size == 0:
            return []

        candidates = self._decode_candidates(matrix)
        if not candidates:
            return []

        boxes = np.asarray([item["box"] for item in candidates], dtype=np.float32)
        scores = np.asarray([float(item["score"]) for item in candidates], dtype=np.float32)
        class_ids = [int(item["class_id"]) for item in candidates]
        keep = self._nms(boxes, scores, self._nms_iou_threshold, self._max_det)

        detections: list[dict[str, Any]] = []
        for idx in keep:
            x1, y1, x2, y2 = boxes[idx].tolist()
            if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 2.0:
                x1 *= self._input_w
                x2 *= self._input_w
                y1 *= self._input_h
                y2 *= self._input_h

            x1 = (x1 - pad_x) / max(scale, 1e-6)
            y1 = (y1 - pad_y) / max(scale, 1e-6)
            x2 = (x2 - pad_x) / max(scale, 1e-6)
            y2 = (y2 - pad_y) / max(scale, 1e-6)

            x1 = max(0.0, min(float(orig_w), x1))
            y1 = max(0.0, min(float(orig_h), y1))
            x2 = max(0.0, min(float(orig_w), x2))
            y2 = max(0.0, min(float(orig_h), y2))
            if x2 <= x1 or y2 <= y1:
                continue

            class_id = class_ids[idx]
            class_name = self._labels[class_id] if 0 <= class_id < len(self._labels) else f"class_{class_id}"
            detections.append(
                {
                    "class": class_name,
                    "bbox": [
                        round(x1 / max(orig_w, 1), 4),
                        round(y1 / max(orig_h, 1), 4),
                        round(x2 / max(orig_w, 1), 4),
                        round(y2 / max(orig_h, 1), 4),
                    ],
                    "confidence": round(float(scores[idx]), 4),
                }
            )
        return detections

    def _select_matrix(self, outputs: list[Any]) -> Any:
        np = self._np
        for value in outputs:
            if isinstance(value, np.ndarray) and value.ndim >= 2 and value.size > 0:
                return value
        return np.zeros((0, 6), dtype=np.float32)

    def _normalize_matrix(self, value: Any) -> Any:
        np = self._np
        arr = value
        if arr.ndim == 4 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim == 3 and arr.shape[-1] >= 6:
            arr = arr.reshape((-1, arr.shape[-1]))
        elif arr.ndim == 3 and arr.shape[1] >= 6:
            arr = np.transpose(arr, (0, 2, 1)).reshape((-1, arr.shape[1]))
        elif arr.ndim == 2:
            pass
        elif arr.ndim == 1 and arr.size >= 6:
            arr = arr.reshape((-1, 6))
        else:
            return np.zeros((0, 6), dtype=np.float32)
        return arr.astype(np.float32, copy=False)

    def _decode_candidates(self, matrix: Any) -> list[dict[str, Any]]:
        np = self._np
        candidates: list[dict[str, Any]] = []
        cols = int(matrix.shape[1]) if matrix.ndim == 2 else 0
        if cols < 6:
            return candidates

        if cols >= 7 and self._looks_like_ssd(matrix):
            for row in matrix:
                score = float(row[2])
                if score < self._conf_threshold:
                    continue
                cls_id = max(0, int(row[1]))
                x1, y1, x2, y2 = [float(v) for v in row[3:7]]
                candidates.append(
                    {"box": [x1, y1, x2, y2], "score": score, "class_id": cls_id}
                )
            return candidates

        if cols > 6:
            adjusted = matrix
            if adjusted.shape[0] in {84, 85, 86} and adjusted.shape[1] > adjusted.shape[0]:
                adjusted = np.transpose(adjusted, (1, 0))
            for row in adjusted:
                obj = float(row[4])
                if obj <= 0.0:
                    continue
                class_scores = row[5:]
                cls_idx = int(np.argmax(class_scores))
                cls_score = float(class_scores[cls_idx])
                score = obj * cls_score
                if score < self._conf_threshold:
                    continue
                cx, cy, w, h = [float(v) for v in row[0:4]]
                x1 = cx - w / 2.0
                y1 = cy - h / 2.0
                x2 = cx + w / 2.0
                y2 = cy + h / 2.0
                candidates.append(
                    {"box": [x1, y1, x2, y2], "score": score, "class_id": cls_idx}
                )
            return candidates

        for row in matrix:
            x1, y1, x2, y2, score, cls_idx = [float(v) for v in row[:6]]
            if score < self._conf_threshold:
                continue
            candidates.append(
                {"box": [x1, y1, x2, y2], "score": score, "class_id": int(cls_idx)}
            )
        return candidates

    @staticmethod
    def _looks_like_ssd(matrix: Any) -> bool:
        if matrix.shape[1] < 7:
            return False
        sample = matrix[: min(8, matrix.shape[0])]
        if sample.size == 0:
            return False
        first_col = sample[:, 0]
        score_col = sample[:, 2]
        return bool((first_col >= -0.1).all() and (first_col <= 1.1).all() and (score_col <= 1.1).all())

    @staticmethod
    def _nms(boxes: Any, scores: Any, iou_threshold: float, max_det: int) -> list[int]:
        np = __import__("numpy")
        order = scores.argsort()[::-1]
        keep: list[int] = []
        while order.size > 0 and len(keep) < max_det:
            i = int(order[0])
            keep.append(i)
            if order.size == 1:
                break
            rest = order[1:]
            xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
            yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
            xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
            yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])

            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            area_i = max(0.0, float((boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])))
            area_rest = np.maximum(0.0, (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1]))
            union = np.maximum(1e-6, area_i + area_rest - inter)
            iou = inter / union
            order = rest[iou <= iou_threshold]
        return keep


app = FastAPI(title="BeYourEyes RealDet Service")
_SERVICE_VERSION = "0.3.0"
_STATE: dict[str, Any] = {
    "ready": False,
    "warmed_up": False,
    "model_id": "",
    "backend": "mock",
    "version": _SERVICE_VERSION,
    "reason": "startup",
    "model_path": "",
}
_RUNTIME: OnnxDetRuntime | None = None


def _labels_from_env() -> list[str]:
    raw = _env_str("BYES_DET_LABELS_CSV", "")
    if not raw:
        return _default_labels()
    labels = [item.strip() for item in raw.split(",") if item.strip()]
    return labels or _default_labels()


def _build_runtime_state() -> dict[str, Any]:
    global _RUNTIME
    backend = _env_str("BYES_BACKEND", "mock").lower()
    model_id = _env_str("BYES_MODEL_ID", "byes-real-det-onnx-cpu-v1")
    weights_dir = Path(_env_str("BYES_WEIGHTS_DIR", "/models"))
    model_file = _env_str("BYES_MODEL_FILE", "model.onnx")
    explicit_model_path = _env_str("BYES_MODEL_PATH", "")
    model_path = Path(explicit_model_path) if explicit_model_path else (weights_dir / model_id / model_file)

    state: dict[str, Any] = {
        "ready": False,
        "warmed_up": False,
        "model_id": model_id,
        "backend": backend,
        "version": _SERVICE_VERSION,
        "reason": "startup",
        "model_path": str(model_path),
    }

    if backend == "mock":
        _RUNTIME = None
        state["ready"] = True
        state["warmed_up"] = True
        state["reason"] = "ok"
        return state

    if backend not in {"onnxruntime", "onnx", "ort"}:
        _RUNTIME = None
        state["reason"] = "unsupported_backend"
        return state

    if not model_path.exists():
        _RUNTIME = None
        state["reason"] = "weights_missing"
        return state

    try:
        runtime = OnnxDetRuntime(
            model_path=model_path,
            input_size=max(64, _env_int("BYES_DET_INPUT_SIZE", 640)),
            conf_threshold=_env_float("BYES_DET_CONF_THRES", 0.25),
            nms_iou_threshold=_env_float("BYES_DET_NMS_IOU", 0.45),
            max_det=max(1, _env_int("BYES_DET_MAX_DET", 50)),
            labels=_labels_from_env(),
        )
        runtime.warmup()
        _RUNTIME = runtime
        state["ready"] = True
        state["warmed_up"] = True
        state["reason"] = "ok"
        in_h, in_w = runtime.input_hw
        state["inputH"] = in_h
        state["inputW"] = in_w
        return state
    except Exception as exc:  # noqa: BLE001
        _RUNTIME = None
        state["reason"] = f"load_error:{exc.__class__.__name__}"
        return state


@app.on_event("startup")
async def _startup() -> None:
    _STATE.update(_build_runtime_state())


def _ensure_ready() -> None:
    if not bool(_STATE.get("ready", False)):
        raise HTTPException(status_code=503, detail="service_not_ready")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ts": _now_ms()}


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ready": bool(_STATE.get("ready", False)),
        "model_id": str(_STATE.get("model_id", "")),
        "backend": str(_STATE.get("backend", "mock")),
        "version": str(_STATE.get("version", _SERVICE_VERSION)),
        "warmed_up": bool(_STATE.get("warmed_up", False)),
        "reason": str(_STATE.get("reason", "")),
    }


@app.post("/infer")
async def infer(
    image: UploadFile = File(...),
    roi: str | None = Form(None),
    tasks: str | None = Form(None),
) -> dict[str, Any]:
    _ensure_ready()
    payload = await image.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty image payload")

    delay_ms = max(0, _env_int("REAL_DET_DELAY_MS", 10))
    timeout_prob = max(0.0, min(1.0, _env_float("REAL_DET_TIMEOUT_PROB", 0.0)))
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)
    if timeout_prob > 0.0 and random.random() < timeout_prob:
        await asyncio.sleep(max(1.0, delay_ms / 1000.0 * 8))

    parsed_roi: dict[str, Any] | None = None
    if roi:
        try:
            parsed = json.loads(roi)
            if isinstance(parsed, dict):
                parsed_roi = parsed
        except json.JSONDecodeError:
            parsed_roi = None

    parsed_tasks: list[str] = []
    if tasks:
        try:
            parsed = json.loads(tasks)
            if isinstance(parsed, list):
                parsed_tasks = [str(item) for item in parsed]
        except json.JSONDecodeError:
            parsed_tasks = []

    started = time.perf_counter()
    if str(_STATE.get("backend", "mock")).lower() == "mock":
        conf = max(0.1, min(0.99, _env_float("REAL_DET_CONFIDENCE", 0.86)))
        detections = [
            {
                "class": os.getenv("REAL_DET_CLASS", "door"),
                "bbox": [0.30, 0.18, 0.64, 0.82],
                "confidence": conf,
            }
        ]
    else:
        if _RUNTIME is None:
            raise HTTPException(status_code=503, detail="runtime_not_initialized")
        detections = await asyncio.to_thread(_RUNTIME.infer, payload)

    if detections:
        best = max(detections, key=lambda item: float(item.get("confidence", 0.0)))
        summary = f"Detected {best.get('class', 'object')} ({float(best.get('confidence', 0.0)):.2f})"
    else:
        summary = "No object detected"

    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "detections": detections,
        "summary": summary,
        "coordFrame": "World",
        "roi": parsed_roi,
        "tasks": parsed_tasks,
        "latencyMs": latency_ms,
        "model_id": _STATE.get("model_id", ""),
        "backend": _STATE.get("backend", "mock"),
    }
