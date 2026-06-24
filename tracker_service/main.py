from __future__ import annotations

import base64
import os
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class TrackRequest(BaseModel):
    image_data: str = ""
    bbox: Optional[List[float]] = None
    label: str = ""
    reset: bool = False


class OnlinePointTracker:
    def __init__(self) -> None:
        self.backend = os.getenv("BYE_TRACKER_BACKEND", "cotracker3_online").strip()
        self.fallback_backend = os.getenv("BYE_TRACKER_FALLBACK", "opencv_mil").strip()
        self.effective_backend = self.backend
        self.device_name = os.getenv("BYE_TRACKER_DEVICE", "cuda").strip()
        self.allow_download = os.getenv("BYE_TRACKER_ALLOW_DOWNLOAD", "0").strip() == "1"
        self.max_width = int(os.getenv("BYE_TRACKER_MAX_WIDTH", "448"))
        self.grid_x = int(os.getenv("BYE_TRACKER_GRID_X", "6"))
        self.grid_y = int(os.getenv("BYE_TRACKER_GRID_Y", "4"))
        self.hybrid_cv = os.getenv("BYE_TRACKER_HYBRID_CV", "1").strip() == "1"
        self.cv_backend_preference = os.getenv("BYE_TRACKER_OPENCV_BACKEND", "lk").strip().lower()
        self.model: Any = None
        self.torch: Any = None
        self.error = ""
        self.frames: List[Any] = []
        self.init_points: Optional[np.ndarray] = None
        self.init_bbox: Optional[List[float]] = None
        self.last_bbox: Optional[List[float]] = None
        self.last_label = ""
        self.last_update = 0.0
        self.frame_shape: Tuple[int, int] = (0, 0)
        self.frame_count = 0
        self.processed_frames = 0
        self.step = 8
        self.window = 16
        self.cv_tracker: Any = None
        self.cv_backend_name = ""
        self.lk_prev_gray: Optional[np.ndarray] = None
        self.lk_points: Optional[np.ndarray] = None

    def status(self) -> Dict[str, Any]:
        efficient_sam2_root = os.path.abspath(os.path.join(os.getcwd(), "third_party", "Efficient-SAM2"))
        return {
            "ok": True,
            "backend": self.backend,
            "effective_backend": self.effective_backend,
            "fallback_backend": self.fallback_backend,
            "model_loaded": self.model is not None,
            "active": self.last_bbox is not None,
            "device": self.device_name,
            "allow_download": self.allow_download,
            "max_width": self.max_width,
            "frames": len(self.frames),
            "step": self.step,
            "window": self.window,
            "hybrid_cv": self.hybrid_cv,
            "opencv_backend": self.cv_backend_name or self.cv_backend_preference,
            "last_label": self.last_label,
            "last_update_age_ms": round((time.time() - self.last_update) * 1000, 1) if self.last_update else None,
            "error": self.error,
            "efficient_sam2": {
                "repo_exists": os.path.isdir(efficient_sam2_root),
                "repo": efficient_sam2_root,
                "role": "2026 VOS calibrator; heavy weights are installed separately",
            },
        }

    def reset(self) -> Dict[str, Any]:
        self.frames = []
        self.init_points = None
        self.init_bbox = None
        self.last_bbox = None
        self.last_label = ""
        self.last_update = 0.0
        self.frame_shape = (0, 0)
        self.frame_count = 0
        self.processed_frames = 0
        self.cv_tracker = None
        self.cv_backend_name = ""
        self.lk_prev_gray = None
        self.lk_points = None
        if self.model is not None and hasattr(self.model, "model"):
            try:
                self.model.model.init_video_online_processing()
            except Exception:
                pass
        return {"ok": True}

    def track(self, image_data: str, bbox: Optional[List[float]], label: str, reset: bool = False) -> Dict[str, Any]:
        if reset:
            self.reset()
        frame = decode_image_data(image_data)
        if self.effective_backend.startswith("opencv"):
            return self._track_opencv(frame, bbox, label)
        try:
            return self._track_cotracker(frame, bbox, label)
        except Exception as exc:
            self.error = repr(exc)[:500]
            if self.fallback_backend == "opencv_mil":
                self.effective_backend = "opencv_mil"
                return self._track_opencv(frame, bbox, label)
            raise

    def _track_cotracker(self, frame: np.ndarray, bbox: Optional[List[float]], label: str) -> Dict[str, Any]:
        started = time.perf_counter()
        tensor, scale, resized_shape, resized_frame = self._frame_to_tensor(frame)
        original_h, original_w = frame.shape[:2]
        self.frame_shape = (original_h, original_w)
        if bbox:
            self._initialize(tensor, resized_frame, bbox, scale, label)
            response = self._response("initialized", scale)
            response["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return response
        if self.last_bbox is None:
            raise RuntimeError("tracker is not initialized")
        self._ensure_model()
        cv_ok = self._track_cv_frame(resized_frame) if self.hybrid_cv and self.cv_tracker is not None else False
        self.frames.append(tensor)
        self.frame_count += 1
        if len(self.frames) > self.window:
            self.frames = self.frames[-self.window :]
        if len(self.frames) < self.window or self.frame_count - self.processed_frames < self.step:
            response = self._response("tracked_cv" if cv_ok else "warmup", scale)
            response["confidence"] = 0.56 if cv_ok else response["confidence"]
            response["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return response
        video = self.torch.stack(self.frames[-self.window :], dim=0).unsqueeze(0).to(self._device())
        with self.torch.inference_mode():
            tracks, visibility = self.model(video_chunk=video, add_support_grid=True)
        latency_ms = (time.perf_counter() - started) * 1000
        self.processed_frames = self.frame_count
        bbox_new, confidence = self._bbox_from_tracks(tracks, visibility)
        if bbox_new:
            self.last_bbox = self._smooth_bbox(self.last_bbox, bbox_new, 0.62) if cv_ok else bbox_new
            if self.hybrid_cv:
                self._init_cv_tracker(resized_frame, self.last_bbox, label or self.last_label)
            self.last_update = time.time()
        response = self._response("tracked", scale)
        response["confidence"] = confidence
        response["latency_ms"] = round(latency_ms, 1)
        return response

    def _track_opencv(self, frame: np.ndarray, bbox: Optional[List[float]], label: str) -> Dict[str, Any]:
        started = time.perf_counter()
        original_h, original_w = frame.shape[:2]
        self.frame_shape = (original_h, original_w)
        if bbox:
            ok = self._init_cv_tracker(frame, bbox, label)
            if not ok:
                raise RuntimeError("opencv tracker initialization failed")
            response = self._response("initialized", 1.0)
            response["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            response["confidence"] = 0.82
            return response
        if self.cv_tracker is None:
            raise RuntimeError("tracker is not initialized")
        ok = self._track_cv_frame(frame)
        state = "tracked" if ok else "lost"
        confidence = 0.72 if ok else 0.0
        response = self._response(state, 1.0)
        response["confidence"] = confidence
        response["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return response

    def _create_cv_tracker(self) -> Any:
        import cv2

        candidates = [self.cv_backend_preference, "kcf", "csrt", "mil"]
        seen = set()
        for name in candidates:
            name = (name or "kcf").lower()
            if name in seen:
                continue
            seen.add(name)
            factories = []
            if name == "kcf":
                factories = ["TrackerKCF_create"]
            elif name == "csrt":
                factories = ["TrackerCSRT_create"]
            elif name == "mil":
                factories = ["TrackerMIL_create"]
            for factory in factories:
                creator = getattr(cv2, factory, None)
                if creator is None and hasattr(cv2, "legacy"):
                    creator = getattr(cv2.legacy, factory, None)
                if creator is None:
                    continue
                self.cv_backend_name = name
                self.effective_backend = f"opencv_{name}" if self.backend != "cotracker3_online" else self.effective_backend
                return creator()
        raise RuntimeError("No OpenCV single-object tracker is available")

    def _init_cv_tracker(self, frame: np.ndarray, bbox: List[float], label: str) -> bool:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = self._clip_bbox([float(v) for v in bbox[:4]], w, h)
        if self.cv_backend_preference == "lk":
            self.cv_backend_name = "lk"
            self.cv_tracker = "lk"
            self.lk_prev_gray = self._gray(frame)
            self.lk_points = self._lk_points_in_bbox(self.lk_prev_gray, [x1, y1, x2, y2])
            if self.lk_points is None or len(self.lk_points) < 4:
                return False
            self.last_bbox = [x1, y1, x2, y2]
            self.last_label = label or self.last_label
            self.last_update = time.time()
            return True
        rect = (int(round(x1)), int(round(y1)), int(round(x2 - x1)), int(round(y2 - y1)))
        tracker = self._create_cv_tracker()
        ok = tracker.init(frame, rect)
        if ok is False:
            return False
        self.cv_tracker = tracker
        self.last_bbox = [x1, y1, x2, y2]
        self.last_label = label or self.last_label
        self.last_update = time.time()
        return True

    def _track_cv_frame(self, frame: np.ndarray) -> bool:
        if self.cv_tracker is None:
            return False
        if self.cv_backend_name == "lk":
            return self._track_lk_frame(frame)
        h, w = frame.shape[:2]
        ok, box = self.cv_tracker.update(frame)
        if not ok:
            self.cv_tracker = None
            return False
        x, y, bw, bh = [float(v) for v in box]
        self.last_bbox = self._clip_bbox([x, y, x + bw, y + bh], w, h)
        self.last_update = time.time()
        return True

    def _track_lk_frame(self, frame: np.ndarray) -> bool:
        if self.lk_prev_gray is None or self.lk_points is None or self.last_bbox is None:
            return False
        import cv2

        gray = self._gray(frame)
        next_points, status, _err = cv2.calcOpticalFlowPyrLK(
            self.lk_prev_gray,
            gray,
            self.lk_points.astype(np.float32),
            None,
            winSize=(21, 21),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03),
        )
        if next_points is None or status is None:
            self.lk_prev_gray = gray
            self.lk_points = None
            return False
        good_prev = self.lk_points[status.reshape(-1) == 1].reshape(-1, 2)
        good_next = next_points[status.reshape(-1) == 1].reshape(-1, 2)
        if len(good_next) < 4:
            self.lk_prev_gray = gray
            self.lk_points = None
            return False
        movement = good_next - good_prev
        dx, dy = np.median(movement, axis=0)
        scale_x, scale_y = self._scale_from_points(good_prev, good_next)
        x1, y1, x2, y2 = self.last_bbox
        cx = (x1 + x2) / 2 + float(dx)
        cy = (y1 + y2) / 2 + float(dy)
        width = max(4.0, (x2 - x1) * scale_x)
        height = max(4.0, (y2 - y1) * scale_y)
        h, w = frame.shape[:2]
        self.last_bbox = self._clip_bbox([cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2], w, h)
        self.last_update = time.time()
        self.lk_prev_gray = gray
        self.lk_points = good_next.reshape(-1, 1, 2)
        if len(self.lk_points) < 10 or self.frame_count % 10 == 0:
            refreshed = self._lk_points_in_bbox(gray, self.last_bbox)
            if refreshed is not None and len(refreshed) >= 8:
                self.lk_points = refreshed
        return True

    def _gray(self, frame: np.ndarray) -> np.ndarray:
        import cv2

        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def _lk_points_in_bbox(self, gray: np.ndarray, bbox: List[float]) -> Optional[np.ndarray]:
        import cv2

        h, w = gray.shape[:2]
        x1, y1, x2, y2 = self._clip_bbox(bbox, w, h)
        mask = np.zeros_like(gray)
        ix1, iy1, ix2, iy2 = int(x1), int(y1), int(x2), int(y2)
        mask[iy1:iy2, ix1:ix2] = 255
        points = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=80,
            qualityLevel=0.01,
            minDistance=max(4, min(ix2 - ix1, iy2 - iy1) // 10),
            mask=mask,
            blockSize=5,
        )
        if points is not None and len(points) >= 8:
            return points.astype(np.float32)
        xs = np.linspace(x1 + max(2.0, (x2 - x1) * 0.15), x2 - max(2.0, (x2 - x1) * 0.15), max(2, self.grid_x))
        ys = np.linspace(y1 + max(2.0, (y2 - y1) * 0.15), y2 - max(2.0, (y2 - y1) * 0.15), max(2, self.grid_y))
        grid = np.array([[[x, y]] for y in ys for x in xs], dtype=np.float32)
        return grid if len(grid) >= 4 else None

    def _initialize(self, tensor: Any, resized_frame: np.ndarray, bbox: List[float], scale: float, label: str) -> None:
        self._ensure_model()
        scaled_bbox = [float(v) * scale for v in bbox[:4]]
        self.init_bbox = scaled_bbox
        self.last_bbox = scaled_bbox
        self.last_label = label or self.last_label
        if self.hybrid_cv:
            self._init_cv_tracker(resized_frame, scaled_bbox, self.last_label)
        self.frames = [tensor]
        self.frame_count = 1
        self.processed_frames = 0
        self.init_points = self._points_in_bbox(scaled_bbox)
        queries = np.zeros((1, len(self.init_points), 3), dtype=np.float32)
        queries[0, :, 1:] = self.init_points
        queries_t = self.torch.from_numpy(queries).to(self._device())
        video = tensor.unsqueeze(0).unsqueeze(0).to(self._device())
        with self.torch.inference_mode():
            self.model(video_chunk=video, is_first_step=True, queries=queries_t, grid_size=0, add_support_grid=True)
        self.last_update = time.time()

    def _ensure_model(self) -> None:
        if self.model is not None:
            return
        if self.backend != "cotracker3_online":
            raise RuntimeError(f"unsupported tracker backend: {self.backend}")
        if not self.allow_download:
            raise RuntimeError(
                "CoTracker3 is not loaded. Set BYE_TRACKER_ALLOW_DOWNLOAD=1 for the tracker sidecar "
                "after you are ready for the first model download."
            )
        try:
            import torch

            self.torch = torch
            model = torch.hub.load("facebookresearch/co-tracker", "cotracker3_online", trust_repo=True)
            model = model.to(self._device()).eval()
            self.model = model
            self.step = int(getattr(model, "step", 8) or 8)
            self.window = self.step * 2
            self.error = ""
        except Exception as exc:
            self.error = repr(exc)[:500]
            raise

    def _device(self) -> str:
        if self.torch is None:
            return self.device_name
        if self.device_name == "auto":
            return "cuda" if self.torch.cuda.is_available() else "cpu"
        if self.device_name == "cuda" and not self.torch.cuda.is_available():
            return "cpu"
        return self.device_name

    def _frame_to_tensor(self, frame: np.ndarray) -> Tuple[Any, float, Tuple[int, int], np.ndarray]:
        self._ensure_torch()
        import cv2

        h, w = frame.shape[:2]
        if w > self.max_width:
            scale = self.max_width / float(w)
            frame = cv2.resize(frame, (self.max_width, max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
        else:
            scale = 1.0
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        tensor = self.torch.from_numpy(rgb).permute(2, 0, 1).float()
        return tensor, scale, frame.shape[:2], frame

    def _ensure_torch(self) -> None:
        if self.torch is not None:
            return
        import torch

        self.torch = torch

    def _points_in_bbox(self, bbox: List[float]) -> np.ndarray:
        x1, y1, x2, y2 = bbox[:4]
        margin_x = max(2.0, (x2 - x1) * 0.12)
        margin_y = max(2.0, (y2 - y1) * 0.12)
        xs = np.linspace(x1 + margin_x, x2 - margin_x, max(2, self.grid_x))
        ys = np.linspace(y1 + margin_y, y2 - margin_y, max(2, self.grid_y))
        return np.array([[x, y] for y in ys for x in xs], dtype=np.float32)

    def _bbox_from_tracks(self, tracks: Any, visibility: Any) -> Tuple[Optional[List[float]], float]:
        if self.init_points is None or self.init_bbox is None:
            return None, 0.0
        pts = tracks[0, -1].detach().float().cpu().numpy()
        vis = visibility[0, -1].detach().bool().cpu().numpy()
        if pts.shape[0] != self.init_points.shape[0]:
            pts = pts[: self.init_points.shape[0]]
            vis = vis[: self.init_points.shape[0]]
        if int(vis.sum()) < max(4, len(vis) // 4):
            return None, float(vis.mean()) if len(vis) else 0.0
        init_visible = self.init_points[vis]
        current_visible = pts[vis]
        deltas = current_visible - init_visible
        dx, dy = np.median(deltas, axis=0)
        x1, y1, x2, y2 = self.init_bbox
        width = max(4.0, x2 - x1)
        height = max(4.0, y2 - y1)
        scale_x, scale_y = self._scale_from_points(init_visible, current_visible)
        width = max(4.0, width * scale_x)
        height = max(4.0, height * scale_y)
        cx = (x1 + x2) / 2 + float(dx)
        cy = (y1 + y2) / 2 + float(dy)
        bbox = [cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2]
        return bbox, float(vis.mean())

    def _scale_from_points(self, init_points: np.ndarray, current_points: np.ndarray) -> Tuple[float, float]:
        if len(init_points) < 6 or len(current_points) < 6:
            return 1.0, 1.0
        init_x = np.percentile(init_points[:, 0], [15, 85])
        init_y = np.percentile(init_points[:, 1], [15, 85])
        cur_x = np.percentile(current_points[:, 0], [15, 85])
        cur_y = np.percentile(current_points[:, 1], [15, 85])
        init_w = max(1.0, float(init_x[1] - init_x[0]))
        init_h = max(1.0, float(init_y[1] - init_y[0]))
        cur_w = max(1.0, float(cur_x[1] - cur_x[0]))
        cur_h = max(1.0, float(cur_y[1] - cur_y[0]))
        return (
            max(0.55, min(1.9, cur_w / init_w)),
            max(0.55, min(1.9, cur_h / init_h)),
        )

    def _smooth_bbox(self, previous: Optional[List[float]], current: List[float], current_weight: float) -> List[float]:
        if not previous:
            return current
        weight = max(0.0, min(1.0, float(current_weight)))
        return [
            float(previous[index]) * (1.0 - weight) + float(current[index]) * weight
            for index in range(4)
        ]

    def _clip_bbox(self, bbox: List[float], width: int, height: int) -> List[float]:
        x1, y1, x2, y2 = bbox[:4]
        x1 = max(0.0, min(float(width - 1), x1))
        y1 = max(0.0, min(float(height - 1), y1))
        x2 = max(x1 + 2.0, min(float(width), x2))
        y2 = max(y1 + 2.0, min(float(height), y2))
        return [x1, y1, x2, y2]

    def _response(self, state: str, scale: float) -> Dict[str, Any]:
        bbox = [round(v / max(scale, 1e-6), 1) for v in self.last_bbox] if self.last_bbox else None
        return {
            "ok": True,
            "state": state,
            "backend": self._backend_label(),
            "bbox": bbox,
            "label": self.last_label,
            "frame_shape": list(self.frame_shape),
            "confidence": 1.0 if state == "initialized" else 0.0,
            "active": bbox is not None,
            "age_ms": round((time.time() - self.last_update) * 1000, 1) if self.last_update else None,
        }

    def _backend_label(self) -> str:
        if self.effective_backend.startswith("opencv"):
            suffix = self.cv_backend_name or self.cv_backend_preference or "opencv"
            return f"opencv_{suffix}"
        if self.backend == "cotracker3_online" and self.cv_tracker is not None and self.hybrid_cv:
            suffix = self.cv_backend_name or self.cv_backend_preference or "opencv"
            return f"cotracker3_online+opencv_{suffix}"
        return self.effective_backend


def decode_image_data(image_data: str) -> np.ndarray:
    import cv2

    if image_data.startswith("data:"):
        _, payload = image_data.split(",", 1)
    else:
        payload = image_data
    raw = base64.b64decode(payload)
    arr = np.frombuffer(raw, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("could not decode image")
    return frame


app = FastAPI(title="Be Your Eyes Tracker Sidecar")
tracker = OnlinePointTracker()


@app.get("/status")
def status() -> Dict[str, Any]:
    return tracker.status()


@app.post("/reset")
def reset() -> Dict[str, Any]:
    return tracker.reset()


@app.post("/track")
def track(req: TrackRequest) -> Dict[str, Any]:
    if not req.image_data:
        raise HTTPException(status_code=400, detail="image_data is required")
    try:
        return tracker.track(req.image_data, req.bbox, req.label, req.reset)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=repr(exc)) from exc
