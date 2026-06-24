from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import math
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .config import settings
from .evidence import Evidence


RISK_CLASSES = {
    "near_obstacle",
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "bench",
    "chair",
    "couch",
    "bed",
    "dining table",
    "potted plant",
    "suitcase",
    "backpack",
}

TARGET_ALIASES = {
    "cup": {"cup", "wine glass"},
    "cell phone": {"cell phone", "remote"},
    "can": {"can", "tin can", "food can", "snack can"},
}

OPEN_VOCAB_DISTRACTOR_PROMPTS = {
    "cup": ["toilet paper roll", "paper roll", "tissue roll", "paper towel roll", "bottle"],
    "can": ["box", "carton", "bottle", "cup", "jar"],
}

OPEN_VOCAB_CONFIRM_TARGETS = {"cup", "can"}

COLOR_THRESHOLDS = {
    "red": 0.18,
    "green": 0.18,
    "blue": 0.16,
    "yellow": 0.14,
    "black": 0.16,
    "white": 0.20,
}

CHROMATIC_COLORS = {"red", "green", "blue", "yellow"}

CLIP_VIT_B32_SHA256 = "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af"

LABEL_ZH = {
    "near_obstacle": "near obstacle",
    "person": "人",
    "chair": "椅子",
    "bed": "床",
    "couch": "沙发",
    "dining table": "桌子",
    "bottle": "瓶子",
    "cup": "杯子",
    "cell phone": "手机",
    "laptop": "电脑",
    "keyboard": "键盘",
    "mouse": "鼠标",
    "remote": "遥控器",
    "tv": "电视",
    "book": "书",
    "wine glass": "酒杯",
    "backpack": "背包",
    "suitcase": "箱子",
    "car": "汽车",
    "bus": "公交车",
    "truck": "卡车",
    "bicycle": "自行车",
    "motorcycle": "摩托车",
    "can": "罐子",
    "tin can": "罐子",
    "food can": "罐子",
    "snack can": "罐子",
    "red can": "红色罐子",
    "red tin can": "红色罐子",
    "red food can": "红色罐子",
    "red snack can": "红色罐子",
    "red cylindrical can": "红色罐子",
    "green can": "绿色罐子",
    "green tin can": "绿色罐子",
    "green food can": "绿色罐子",
    "green snack can": "绿色罐子",
    "green cylindrical can": "绿色罐子",
    "blue can": "蓝色罐子",
    "yellow can": "黄色罐子",
}

LABEL_ZH.update(
    {
        "toilet paper roll": "卷纸",
        "paper roll": "纸卷",
        "tissue roll": "卷纸",
        "paper towel roll": "厨房纸卷",
    }
)


class VisionToolchain:
    def __init__(self) -> None:
        self._detector = None
        self._yoloe = None
        self._world = None
        self._depth_model = None
        self._sam3 = None
        self._yoloe_classes: Tuple[str, ...] = ()
        self._yoloe_error = ""
        self._yoloe_disabled_until = 0.0
        self._depth_error = ""
        self._depth_disabled_until = 0.0
        self._last_depth: Optional[Dict[str, Any]] = None
        self._last_depth_at = 0.0
        self._sam3_error = ""
        self._sam3_disabled_until = 0.0
        self._world_classes: Tuple[str, ...] = ()
        self._world_error = ""
        self._world_disabled_until = 0.0
        self._clip_checked = False
        self._clip_checked_at = 0.0
        self._clip_cache_ok = False
        self._clip_cache_message = ""
        self._hands = None
        self._hand_connections = None
        self._hands_error = ""
        self._ocr = None
        self._rapid_ocr = None
        self._camera = None
        self._camera_index = settings.camera_index
        self._camera_thread = None
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_frame_at = 0.0
        self._frame_count = 0
        self._camera_error = ""
        self._camera_running = False
        self._lock = threading.Lock()
        self._camera_lock = threading.Lock()
        self._last_frame_gray: Optional[np.ndarray] = None
        self._last_quality_at = 0.0
        self._last_hand_states: Dict[str, Dict[str, Any]] = {}

    def decode_image(self, image_data: str) -> np.ndarray:
        if "," in image_data:
            image_data = image_data.split(",", 1)[1]
        raw = base64.b64decode(image_data)
        arr = np.frombuffer(raw, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Could not decode image")
        return frame

    def encode_image(self, frame: np.ndarray, width: int = 960) -> str:
        buf = self.jpeg_bytes(frame, width=width, quality=86)
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")

    def jpeg_bytes(self, frame: np.ndarray, width: int = 960, quality: int = 82) -> np.ndarray:
        if frame.shape[1] > width:
            scale = width / frame.shape[1]
            frame = cv2.resize(frame, (width, int(frame.shape[0] * scale)))
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise ValueError("Could not encode image")
        return buf

    def _resolve_optional_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = settings.root_dir / path
        return path

    def capture_server_frame(self) -> np.ndarray:
        self._ensure_camera_thread()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            with self._camera_lock:
                if self._latest_frame is not None:
                    if time.time() - self._latest_frame_at < 1.5:
                        return self._latest_frame.copy()
                error = self._camera_error
            if error:
                raise RuntimeError(error)
            time.sleep(0.03)
        raise RuntimeError("No cached camera frame is available yet")

    def camera_status(self) -> Dict[str, Any]:
        with self._camera_lock:
            shape = list(self._latest_frame.shape) if self._latest_frame is not None else None
            frame_age = time.time() - self._latest_frame_at if self._latest_frame_at else None
            return {
                "index": self._camera_index,
                "running": self._camera_thread is not None and self._camera_thread.is_alive(),
                "error": self._camera_error,
                "frame_age_ms": round(frame_age * 1000, 1) if frame_age is not None else None,
                "frame_shape": shape,
                "frame_count": self._frame_count,
            }

    def set_camera_index(self, index: int) -> Dict[str, Any]:
        if index < 0 or index > 10:
            raise ValueError("Camera index must be between 0 and 10")
        self.stop_camera()
        with self._camera_lock:
            self._camera_index = index
            self._camera_error = ""
            self._latest_frame = None
            self._latest_frame_at = 0.0
            self._frame_count = 0
        self._ensure_camera_thread()
        return self.camera_status()

    def stop_camera(self) -> None:
        with self._camera_lock:
            self._camera_running = False
            cap = self._camera
            thread = self._camera_thread
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._camera_lock:
            if self._camera_thread is thread:
                self._camera_thread = None
            if self._camera is cap:
                self._camera = None

    def open_vocab_status(self) -> Dict[str, Any]:
        clip_status = self._clip_cache_status()
        disabled_ms = max(0.0, (self._world_disabled_until - time.time()) * 1000)
        if clip_status["ok"] and self._world_error.startswith("CLIP ViT-B/32 cache"):
            self._world_error = ""
        return {
            "enabled": settings.enable_yolo_world,
            "available": bool(settings.enable_yolo_world and clip_status["ok"] and disabled_ms <= 0),
            "model": settings.yolo_world_model,
            "classes": list(self._world_classes),
            "clip_cache_ok": clip_status["ok"],
            "clip_cache_path": clip_status["path"],
            "disabled_for_ms": round(disabled_ms, 1),
            "error": self._world_error or clip_status["message"],
        }

    def yoloe_status(self) -> Dict[str, Any]:
        mobileclip = self._mobileclip_asset_status()
        disabled_ms = max(0.0, (self._yoloe_disabled_until - time.time()) * 1000)
        model_path = self._resolve_optional_path(settings.yoloe_model)
        return {
            "enabled": settings.enable_yoloe,
            "available": bool(
                settings.enable_yoloe
                and model_path.exists()
                and mobileclip["ok"]
                and disabled_ms <= 0
            ),
            "model": str(model_path),
            "model_exists": model_path.exists(),
            "classes": list(self._yoloe_classes),
            "mobileclip_ok": mobileclip["ok"],
            "mobileclip_path": mobileclip["path"],
            "disabled_for_ms": round(disabled_ms, 1),
            "error": self._yoloe_error or mobileclip["message"],
        }

    def depth_status(self) -> Dict[str, Any]:
        model_path = self._resolve_optional_path(settings.depth_model)
        disabled_ms = max(0.0, (self._depth_disabled_until - time.time()) * 1000)
        runtime_ok = importlib.util.find_spec("depth_anything_3") is not None
        return {
            "enabled": settings.enable_depth,
            "available": bool(settings.enable_depth and model_path.exists() and runtime_ok and disabled_ms <= 0),
            "backend": "depth_anything_3",
            "model": str(model_path),
            "model_exists": model_path.exists(),
            "runtime_ok": runtime_ok,
            "process_res": settings.depth_process_res,
            "interval": settings.depth_interval,
            "cached_age_ms": round((time.time() - self._last_depth_at) * 1000, 1) if self._last_depth_at else None,
            "disabled_for_ms": round(disabled_ms, 1),
            "error": self._depth_error if self._depth_error else ("" if runtime_ok else "depth_anything_3 is not installed"),
        }

    def hand_status(self) -> Dict[str, Any]:
        model_path = self._resolve_optional_path(settings.hand_model_path)
        return {
            "enabled": settings.enable_hand_tracking,
            "available": bool(self._hands is not None and not self._hands_error),
            "backend": "mediapipe",
            "model": str(model_path),
            "model_exists": model_path.exists(),
            "error": self._hands_error,
        }

    def sam3_status(self) -> Dict[str, Any]:
        model_path = self._resolve_optional_path(settings.sam3_model)
        disabled_ms = max(0.0, (self._sam3_disabled_until - time.time()) * 1000)
        if model_path.exists() and self._sam3_error.startswith("SAM3 model not found"):
            self._sam3_error = ""
        return {
            "enabled": settings.enable_sam3,
            "available": bool(settings.enable_sam3 and model_path.exists() and disabled_ms <= 0),
            "model": str(model_path),
            "model_exists": model_path.exists(),
            "disabled_for_ms": round(disabled_ms, 1),
            "error": self._sam3_error,
        }

    def _ensure_camera_thread(self) -> None:
        with self._camera_lock:
            if self._camera_thread is not None and self._camera_thread.is_alive():
                return
            self._camera_running = True
            self._camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
            self._camera_thread.start()

    def _camera_loop(self) -> None:
        cap = None
        try:
            cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
            self._safe_camera_set(cap, cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self._safe_camera_set(cap, cv2.CAP_PROP_FRAME_WIDTH, settings.camera_width)
            self._safe_camera_set(cap, cv2.CAP_PROP_FRAME_HEIGHT, settings.camera_height)
            self._safe_camera_set(cap, cv2.CAP_PROP_FPS, settings.camera_fps)
            self._safe_camera_set(cap, cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception as exc:
            with self._camera_lock:
                self._camera_error = f"Camera setup failed for index {self._camera_index}: {repr(exc)[:180]}"
                self._camera_running = False
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            return
        if not cap.isOpened():
            with self._camera_lock:
                self._camera_error = f"Could not open camera index {self._camera_index}"
                self._camera_running = False
            try:
                cap.release()
            except Exception:
                pass
            return
        with self._camera_lock:
            self._camera = cap
            self._camera_error = ""
        try:
            while self._camera_running:
                ok, frame = cap.read()
                if ok and frame is not None:
                    with self._camera_lock:
                        self._latest_frame = frame
                        self._latest_frame_at = time.time()
                        self._frame_count += 1
                else:
                    with self._camera_lock:
                        self._camera_error = "Could not read a frame from the server camera"
                    time.sleep(0.1)
                time.sleep(0.001)
        finally:
            try:
                cap.release()
            except Exception:
                pass
            with self._camera_lock:
                if self._camera is cap:
                    self._camera = None
                self._camera_running = False

    def _safe_camera_set(self, cap: Any, prop: int, value: Any) -> None:
        try:
            cap.set(prop, value)
        except Exception:
            pass

    def analyze(self, frame: np.ndarray, plan: Dict[str, Any]) -> Dict[str, Any]:
        start = time.time()
        quality = self.assess_quality(frame)
        evidence: List[Evidence] = []
        annotated = frame.copy()
        stats: Dict[str, Any] = {}

        tools = set(plan.get("tools", []))
        target_en = str(plan.get("target_en") or "").strip()
        target_zh = str(plan.get("target_zh") or "").strip()
        target_color = str(plan.get("target_color") or "").strip().lower()
        target_color_zh = str(plan.get("target_color_zh") or "").strip()
        target_prompts = [str(item).strip() for item in plan.get("target_prompts", []) if str(item).strip()]
        if target_en and target_en not in target_prompts:
            target_prompts.insert(0, target_en)

        hand_items: List[Evidence] = []
        needs_hand_tracking = "hand" in tools or ("detect" in tools and settings.enable_hand_tracking)
        if needs_hand_tracking:
            hand_items, annotated = self.detect_hands(frame, annotated)
            evidence.extend(hand_items)
            stats["hands"] = sum(1 for item in hand_items if item.type == "hand")
            stats["hand_tracking"] = self.hand_status()

        if "detect" in tools:
            objects, annotated = self.detect_objects(
                frame,
                annotated,
                target_en or None,
                target_prompts,
                target_zh,
                target_color,
                target_color_zh,
                hand_items,
            )
            evidence.extend(objects)
            stats["objects"] = sum(1 for item in objects if item.type == "object")
            stats["yoloe"] = self.yoloe_status()
            stats["open_vocab"] = self.open_vocab_status()
            stats["sam3"] = self.sam3_status()

        if "ocr" in tools:
            texts, annotated, ocr_status = self.read_text(frame, annotated)
            evidence.extend(texts)
            stats["texts"] = len(texts)
            stats["ocr_status"] = ocr_status

        if settings.enable_depth and ({"detect", "hand"} & tools):
            depth_result = self.estimate_depth(frame)
            if depth_result:
                self._attach_depth_to_evidence(evidence, depth_result, frame.shape)
                obstacle = self._depth_obstacle_evidence(depth_result, frame.shape)
                if obstacle:
                    evidence.append(obstacle)
                    self._draw_box(annotated, obstacle, color=(40, 210, 210))
                stats["depth"] = self._depth_result_stats(depth_result)
            else:
                stats["depth"] = self.depth_status()

        safety = self.assess_safety(evidence, quality, frame.shape)
        stats["latency_ms"] = round((time.time() - start) * 1000, 1)
        return {
            "quality": quality,
            "evidence": evidence,
            "safety": safety,
            "annotated_image": self.encode_image(annotated),
            "stats": stats,
        }

    def warmup_async(self) -> None:
        thread = threading.Thread(target=self._warmup, daemon=True)
        thread.start()

    def _warmup(self) -> None:
        try:
            if settings.enable_hand_tracking:
                self._get_hands()
        except Exception:
            pass
        try:
            blank = np.full((360, 640, 3), 240, dtype=np.uint8)
            self.detect_objects(blank, blank.copy(), None)
        except Exception:
            pass
        try:
            if settings.enable_yolo_world:
                blank = np.full((360, 640, 3), 240, dtype=np.uint8)
                positive = self._normalize_positive_world_prompts("cup", ["cup", "mug", "drinking cup", "tumbler"])
                distractors = self._distractor_world_prompts("cup")
                prompts = self._merge_prompts(positive, distractors)
                self._detect_open_vocab(blank, blank.copy(), "cup", prompts, positive, distractors, "水杯", "", "")
        except Exception:
            pass
        try:
            self._get_rapid_ocr()
        except Exception:
            pass

    def assess_quality(self, frame: np.ndarray) -> Dict[str, Any]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        dark_ratio = float(np.mean(gray < 24))
        bright_ratio = float(np.mean(gray > 245))
        motion_score = 0.0
        now = time.time()
        motion_gray = cv2.resize(gray, (320, 180), interpolation=cv2.INTER_AREA)
        if (
            self._last_frame_gray is not None
            and self._last_frame_gray.shape == motion_gray.shape
            and now - self._last_quality_at < 1.2
        ):
            diff = cv2.absdiff(motion_gray, self._last_frame_gray)
            motion_score = float(np.mean(diff))
        self._last_frame_gray = motion_gray
        self._last_quality_at = now

        issues: List[str] = []
        if brightness < 45:
            issues.append("too_dark")
        if blur < 20:
            issues.append("severely_blurry")
        elif blur < 55:
            issues.append("blurry")
        if dark_ratio > 0.82 or (bright_ratio > 0.96 and blur < 20):
            issues.append("possibly_obstructed")
        if motion_score > 75:
            issues.append("moving_fast")

        blocking_issues = [issue for issue in issues if issue in {"too_dark", "severely_blurry", "possibly_obstructed"}]
        speech = ""
        if "too_dark" in issues:
            speech = "画面偏暗，请先停一下并调整朝向。"
        elif "severely_blurry" in issues:
            speech = "画面有些模糊，请保持摄像头稳定。"
        elif "possibly_obstructed" in issues:
            speech = "摄像头可能被遮挡，请重新对准。"

        return {
            "usable": len(blocking_issues) == 0,
            "issues": issues,
            "blocking_issues": blocking_issues,
            "motion_warning": "moving_fast" in issues,
            "brightness": round(brightness, 2),
            "blur": round(blur, 2),
            "motion": round(motion_score, 2),
            "speech": speech,
        }

    def detect_objects(
        self,
        frame: np.ndarray,
        annotated: np.ndarray,
        target_en: Optional[str],
        target_prompts: Optional[List[str]] = None,
        target_zh: str = "",
        target_color: str = "",
        target_color_zh: str = "",
        hand_regions: Optional[List[Evidence]] = None,
    ) -> Tuple[List[Evidence], np.ndarray]:
        items: List[Evidence] = []
        positive_prompts = self._normalize_positive_world_prompts(target_en, target_prompts, target_color)
        distractor_prompts = self._distractor_world_prompts(target_en, target_color)
        prompts = self._merge_prompts(positive_prompts, distractor_prompts)
        base_yolo_mode = settings.base_yolo_mode
        run_base_yolo = base_yolo_mode == "always" or (base_yolo_mode == "scene" and not prompts)

        yoloe_items: List[Evidence] = []
        if prompts and settings.enable_yoloe:
            yoloe_items = self._detect_yoloe(
                frame,
                annotated,
                target_en or "",
                prompts,
                positive_prompts,
                distractor_prompts,
                target_zh,
                target_color,
                target_color_zh,
            )
            items.extend(yoloe_items)
            self._apply_target_contrast(items, target_en or "")
            self._dedupe_target_matches(items)

        has_yoloe_target = any(
            item.type == "object" and item.attributes.get("target_match")
            for item in yoloe_items
        )
        sam3_items: List[Evidence] = []
        if prompts and settings.enable_sam3 and not has_yoloe_target:
            sam3_items = self._detect_sam3(
                frame,
                annotated,
                target_en or "",
                prompts,
                positive_prompts,
                distractor_prompts,
                target_zh,
                target_color,
                target_color_zh,
            )
            items.extend(sam3_items)
            self._apply_target_contrast(items, target_en or "")
            self._dedupe_target_matches(items)

        has_sam3_target = any(
            item.type == "object" and item.attributes.get("target_match")
            for item in sam3_items
        )
        if prompts and settings.enable_yolo_world and not (has_yoloe_target or has_sam3_target):
            world_items = self._detect_open_vocab(
                frame,
                annotated,
                target_en or "",
                prompts,
                positive_prompts,
                distractor_prompts,
                target_zh,
                target_color,
                target_color_zh,
            )
            items.extend(world_items)
            self._apply_target_contrast(items, target_en or "")
            self._dedupe_target_matches(items)

        if run_base_yolo:
            items.extend(
                self._detect_base_yolo(
                    frame,
                    annotated,
                    target_en=target_en,
                    target_zh=target_zh,
                    target_color=target_color,
                    target_color_zh=target_color_zh,
                    hand_regions=hand_regions,
                )
            )
        return items, annotated

    def _detect_base_yolo(
        self,
        frame: np.ndarray,
        annotated: np.ndarray,
        target_en: Optional[str],
        target_zh: str,
        target_color: str,
        target_color_zh: str,
        hand_regions: Optional[List[Evidence]] = None,
    ) -> List[Evidence]:
        base_model = self._get_detector()
        base_result = base_model.predict(
            frame,
            imgsz=640,
            conf=settings.detector_confidence,
            device=self._device(),
            verbose=False,
        )[0]
        return self._detections_from_result(
            base_result,
            frame,
            annotated,
            source="yolo",
            color=(30, 130, 255),
            target_en=target_en,
            target_prompts=[],
            target_zh=target_zh,
            is_open_vocab=False,
            target_color=target_color,
            target_color_zh=target_color_zh,
            hand_regions=hand_regions,
        )

    def _detect_yoloe(
        self,
        frame: np.ndarray,
        annotated: np.ndarray,
        target_en: str,
        prompts: List[str],
        positive_prompts: List[str],
        distractor_prompts: List[str],
        target_zh: str,
        target_color: str,
        target_color_zh: str,
    ) -> List[Evidence]:
        now = time.time()
        if now < self._yoloe_disabled_until:
            return [self._yoloe_status_evidence(target_en, "temporarily_disabled")]

        model_path = self._resolve_optional_path(settings.yoloe_model)
        if not model_path.exists():
            self._yoloe_error = f"YOLOE model not found: {model_path}"
            self._yoloe_disabled_until = now + 30
            return [self._yoloe_status_evidence(target_en, self._yoloe_error)]

        mobileclip = self._mobileclip_asset_status()
        if not mobileclip["ok"]:
            self._yoloe_error = mobileclip["message"]
            self._yoloe_disabled_until = now + 30
            return [self._yoloe_status_evidence(target_en, self._yoloe_error)]

        try:
            yoloe = self._get_yoloe()
            classes = tuple(prompt for prompt in prompts[:12] if prompt and prompt != " ")
            if classes != self._yoloe_classes:
                yoloe.set_classes(list(classes))
                self._yoloe_classes = classes
            result = yoloe.predict(
                frame,
                imgsz=640,
                conf=settings.yoloe_confidence,
                device=self._device(),
                verbose=False,
            )[0]
            self._yoloe_error = ""
            return self._detections_from_result(
                result,
                frame,
                annotated,
                source="yoloe",
                color=(80, 190, 70),
                target_en=target_en,
                target_prompts=list(classes),
                positive_prompts=positive_prompts,
                distractor_prompts=distractor_prompts,
                target_zh=target_zh,
                is_open_vocab=True,
                target_color=target_color,
                target_color_zh=target_color_zh,
            )
        except Exception as exc:
            self._yoloe_error = repr(exc)[:300]
            self._yoloe_disabled_until = time.time() + 120
            return [self._yoloe_status_evidence(target_en, self._yoloe_error)]

    def _detect_sam3(
        self,
        frame: np.ndarray,
        annotated: np.ndarray,
        target_en: str,
        prompts: List[str],
        positive_prompts: List[str],
        distractor_prompts: List[str],
        target_zh: str,
        target_color: str,
        target_color_zh: str,
    ) -> List[Evidence]:
        now = time.time()
        if now < self._sam3_disabled_until:
            return [self._sam3_status_evidence(target_en, "temporarily_disabled")]

        model_path = self._resolve_optional_path(settings.sam3_model)
        if not model_path.exists():
            self._sam3_error = f"SAM3 model not found: {model_path}"
            return []

        try:
            predictor = self._get_sam3()
            predictor.set_image(frame)
            results = predictor(text=prompts[:12], stream=False)
            result = results[0] if isinstance(results, list) else list(results)[0]
            self._sam3_error = ""
            return self._detections_from_result(
                result,
                frame,
                annotated,
                source="sam3",
                color=(70, 220, 255),
                target_en=target_en,
                target_prompts=prompts[:12],
                positive_prompts=positive_prompts,
                distractor_prompts=distractor_prompts,
                target_zh=target_zh,
                is_open_vocab=True,
                target_color=target_color,
                target_color_zh=target_color_zh,
            )
        except Exception as exc:
            self._sam3_error = repr(exc)[:300]
            if "SimpleTokenizer" in self._sam3_error:
                self._sam3_error += "；请安装 Ultralytics CLIP：pip uninstall clip -y && pip install git+https://github.com/ultralytics/CLIP.git"
            self._sam3_disabled_until = time.time() + 120
            return [self._sam3_status_evidence(target_en, self._sam3_error)]

    def _detect_open_vocab(
        self,
        frame: np.ndarray,
        annotated: np.ndarray,
        target_en: str,
        prompts: List[str],
        positive_prompts: List[str],
        distractor_prompts: List[str],
        target_zh: str,
        target_color: str,
        target_color_zh: str,
    ) -> List[Evidence]:
        now = time.time()
        if now < self._world_disabled_until:
            return [self._open_vocab_status_evidence(target_en, "temporarily_disabled")]

        clip_status = self._clip_cache_status()
        if not clip_status["ok"]:
            self._world_error = clip_status["message"]
            self._world_disabled_until = now + 60
            return [self._open_vocab_status_evidence(target_en, self._world_error)]

        try:
            world = self._get_world()
            classes = tuple(prompts[:12])
            if classes != self._world_classes and hasattr(world, "set_classes"):
                self._set_world_classes(world, classes)
                self._world_classes = classes
            result = world.predict(
                frame,
                imgsz=640,
                conf=settings.yolo_world_confidence,
                device=self._device(),
                verbose=False,
            )[0]
            self._world_error = ""
            return self._detections_from_result(
                result,
                frame,
                annotated,
                source="yolo_world",
                color=(180, 80, 255),
                target_en=target_en,
                target_prompts=list(classes),
                positive_prompts=positive_prompts,
                distractor_prompts=distractor_prompts,
                target_zh=target_zh,
                is_open_vocab=True,
                target_color=target_color,
                target_color_zh=target_color_zh,
            )
        except Exception as exc:
            self._world_error = repr(exc)[:300]
            self._world_disabled_until = time.time() + 120
            return [self._open_vocab_status_evidence(target_en, self._world_error)]

    def _get_sam3(self) -> Any:
        if self._sam3 is not None:
            return self._sam3
        model_path = self._resolve_optional_path(settings.sam3_model)
        if not model_path.exists():
            raise FileNotFoundError(f"SAM3 model not found: {model_path}")
        from ultralytics.models.sam import SAM3SemanticPredictor

        overrides = {
            "conf": settings.sam3_confidence,
            "task": "segment",
            "mode": "predict",
            "model": str(model_path),
            "half": True,
            "save": False,
            "verbose": False,
            "device": self._device(),
        }
        self._sam3 = SAM3SemanticPredictor(overrides=overrides)
        return self._sam3

    def _detections_from_result(
        self,
        result: Any,
        frame: np.ndarray,
        annotated: np.ndarray,
        source: str,
        color: Tuple[int, int, int],
        target_en: Optional[str],
        target_prompts: List[str],
        target_zh: str,
        is_open_vocab: bool,
        positive_prompts: Optional[List[str]] = None,
        distractor_prompts: Optional[List[str]] = None,
        target_color: str = "",
        target_color_zh: str = "",
        hand_regions: Optional[List[Evidence]] = None,
    ) -> List[Evidence]:
        h, w = frame.shape[:2]
        items: List[Evidence] = []
        names = result.names or {}
        masks_np = None
        result_masks = getattr(result, "masks", None)
        if result_masks is not None and getattr(result_masks, "data", None) is not None:
            try:
                masks_np = result_masks.data.detach().cpu().numpy()
            except Exception:
                masks_np = None
        positive_set = {self._normalize_prompt(prompt) for prompt in (positive_prompts or [])}
        distractor_set = {self._normalize_prompt(prompt) for prompt in (distractor_prompts or [])}
        for det_index, box in enumerate(result.boxes):
            cls_id = int(box.cls[0])
            label = self._class_name(names, cls_id)
            conf = float(box.conf[0])
            label_key = self._normalize_prompt(label)
            target_distractor = bool(is_open_vocab and label_key in distractor_set)
            if is_open_vocab:
                target_match = bool(label_key in positive_set or self._matches_target(label, target_en))
            else:
                target_match = self._matches_target(label, target_en)
            requires_open_vocab_confirmation = bool(
                target_match and not is_open_vocab and self._normalize_prompt(target_en) in OPEN_VOCAB_CONFIRM_TARGETS
            )
            if requires_open_vocab_confirmation:
                target_match = False
            min_conf = settings.yolo_world_confidence if is_open_vocab else self._min_conf_for_label(label)
            if target_match and not is_open_vocab:
                min_conf = min(min_conf, 0.32)
            if conf < min_conf:
                continue
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
            if self._is_hand_person_false_positive(label, (x1, y1, x2, y2), hand_regions or [], (w, h)):
                continue
            position = self._position_from_box((x1, y1, x2, y2), w, h)
            area_ratio = max(0.0, (x2 - x1) * (y2 - y1) / float(w * h))
            mask_area_ratio = None
            mask_bbox_fill = None
            if masks_np is not None and det_index < len(masks_np):
                mask = np.asarray(masks_np[det_index], dtype=np.float32)
                if mask.shape[:2] != (h, w):
                    mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)
                mask_bool = mask > 0.45
                mask_pixels = float(mask_bool.sum())
                if mask_pixels > 0:
                    mask_area_ratio = mask_pixels / float(w * h)
                    box_pixels = max(1.0, (x2 - x1) * (y2 - y1))
                    mask_bbox_fill = min(1.0, mask_pixels / box_pixels)
            color_scores = self._color_scores(frame, (x1, y1, x2, y2))
            color_score = color_scores.get(target_color, 0.0) if target_color else 0.0
            competing_color, competing_score = self._dominant_competing_color(color_scores, target_color)
            weak_target_color = target_color and color_score < COLOR_THRESHOLDS.get(target_color, 0.10)
            dominated_by_other_color = bool(
                target_color
                and target_color in CHROMATIC_COLORS
                and competing_color
                and competing_score >= max(0.15, color_score * 1.35)
                and competing_score - color_score >= 0.06
            )
            container_surrogate_match = self._is_container_surrogate_target(
                label_key,
                target_en,
                target_color,
                color_score,
                competing_color,
                competing_score,
                area_ratio,
                (x1, y1, x2, y2),
            )
            if container_surrogate_match:
                target_match = True
                target_distractor = False
            color_mismatch = bool(target_match and (weak_target_color or dominated_by_other_color))
            if container_surrogate_match:
                color_mismatch = False
            if color_mismatch:
                target_match = False
            ttl = 1.6 if target_match else 0.8 if label in RISK_CLASSES or area_ratio > 0.16 else 2.2
            label_zh = target_zh if target_match and target_zh else LABEL_ZH.get(label, label)
            if color_mismatch and target_color_zh:
                label_zh = f"非{target_color_zh}{LABEL_ZH.get(label, label)}"
            if requires_open_vocab_confirmation:
                label_zh = "疑似罐状物" if self._normalize_prompt(target_en) == "can" else "疑似杯状物"
            item = Evidence(
                type="object",
                label=label,
                source=source,
                confidence=round(conf, 4),
                timestamp=time.time(),
                ttl=ttl,
                position=position,
                bbox=[round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                attributes={
                    "area_ratio": round(area_ratio, 4),
                    "mask_area_ratio": round(mask_area_ratio, 4) if mask_area_ratio is not None else None,
                    "mask_bbox_fill": round(mask_bbox_fill, 4) if mask_bbox_fill is not None else None,
                    "target": target_en or "",
                    "target_color": target_color,
                    "target_color_zh": target_color_zh,
                    "color_score": round(color_score, 4) if target_color else None,
                    "color_scores": {key: round(value, 4) for key, value in color_scores.items()},
                    "competing_color": competing_color,
                    "competing_color_score": round(competing_score, 4) if competing_color else None,
                    "target_color_mismatch": color_mismatch,
                    "container_surrogate_match": container_surrogate_match,
                    "target_prompts": target_prompts,
                    "target_match": target_match,
                    "target_distractor": target_distractor,
                    "requires_open_vocab_confirmation": requires_open_vocab_confirmation,
                    "label_zh": label_zh,
                },
            )
            items.append(item)
            if masks_np is not None and det_index < len(masks_np):
                self._draw_mask(annotated, masks_np[det_index], color=color)
            self._draw_box(annotated, item, color=color)
        return items

    def _color_score(self, frame: np.ndarray, bbox: Tuple[float, float, float, float], color_name: str) -> float:
        return self._color_scores(frame, bbox).get(self._normalize_prompt(color_name), 0.0)

    def _is_container_surrogate_target(
        self,
        label_key: str,
        target_en: Optional[str],
        target_color: str,
        color_score: float,
        competing_color: Optional[str],
        competing_score: float,
        area_ratio: float,
        bbox: Tuple[float, float, float, float],
    ) -> bool:
        if self._normalize_prompt(target_en or "") != "can" or not target_color:
            return False
        color_prefix = f"{self._normalize_prompt(target_color)} "
        container_label = label_key[len(color_prefix) :] if label_key.startswith(color_prefix) else label_key
        if container_label not in {"cup", "mug", "drinking cup", "tumbler", "jar", "tin can", "food can", "snack can"}:
            return False
        threshold = max(0.12, COLOR_THRESHOLDS.get(target_color, 0.10) * 0.72)
        if color_score < threshold:
            return False
        if competing_color and competing_score >= max(0.22, color_score * 1.55) and competing_score - color_score >= 0.08:
            return False
        x1, y1, x2, y2 = bbox
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        aspect = height / width
        return area_ratio >= 0.018 and 0.65 <= aspect <= 4.2

    def _color_scores(self, frame: np.ndarray, bbox: Tuple[float, float, float, float]) -> Dict[str, float]:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        ix1 = max(0, min(w - 1, int(x1)))
        iy1 = max(0, min(h - 1, int(y1)))
        ix2 = max(0, min(w, int(x2)))
        iy2 = max(0, min(h, int(y2)))
        if ix2 <= ix1 or iy2 <= iy1:
            return {}
        crop = frame[iy1:iy2, ix1:ix2]
        if crop.size == 0:
            return {}
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0]
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        masks = {
            "red": ((hue <= 10) | (hue >= 170)) & (sat >= 55) & (val >= 45),
            "green": (hue >= 35) & (hue <= 85) & (sat >= 45) & (val >= 45),
            "blue": (hue >= 90) & (hue <= 130) & (sat >= 45) & (val >= 45),
            "yellow": (hue >= 18) & (hue <= 38) & (sat >= 45) & (val >= 55),
            "black": val <= 55,
            "white": (sat <= 35) & (val >= 180),
        }
        return {name: float(np.mean(mask)) for name, mask in masks.items()}

    def _dominant_competing_color(self, scores: Dict[str, float], target_color: str) -> Tuple[str, float]:
        target_color = self._normalize_prompt(target_color)
        competitors = {
            color: score
            for color, score in scores.items()
            if color in CHROMATIC_COLORS and color != target_color
        }
        if not competitors:
            return "", 0.0
        color, score = max(competitors.items(), key=lambda item: item[1])
        return color, score

    def _class_name(self, names: Any, cls_id: int) -> str:
        if isinstance(names, dict):
            return str(names.get(cls_id, cls_id))
        if isinstance(names, list) and 0 <= cls_id < len(names):
            return str(names[cls_id])
        return str(cls_id)

    def _matches_target(self, label: str, target_en: Optional[str]) -> bool:
        if not target_en:
            return False
        normalized_label = label.strip().lower()
        normalized_target = target_en.strip().lower()
        aliases = {item.lower() for item in TARGET_ALIASES.get(normalized_target, {normalized_target})}
        return normalized_label in aliases

    def _normalize_positive_world_prompts(
        self, target_en: Optional[str], target_prompts: Optional[List[str]], target_color: str = ""
    ) -> List[str]:
        result: List[str] = []
        prompt_candidates = list(target_prompts or [])
        if not target_color:
            prompt_candidates.insert(0, target_en or "")
        elif target_en and target_en not in prompt_candidates:
            prompt_candidates.append(target_en)
        for prompt in prompt_candidates:
            prompt = self._normalize_prompt(prompt)
            if prompt and prompt not in result:
                result.append(prompt)
        return result[:6]

    def _distractor_world_prompts(self, target_en: Optional[str], target_color: str = "") -> List[str]:
        target = self._normalize_prompt(target_en or "")
        target_color = self._normalize_prompt(target_color)
        result: List[str] = []
        if target_color and target in {"can", "cup"}:
            other_colors = [color for color in ("red", "green", "blue", "yellow", "black", "white") if color != target_color]
            result.extend(f"{color} {target}" for color in other_colors[:3])
        for prompt in OPEN_VOCAB_DISTRACTOR_PROMPTS.get(target, []):
            if target_color:
                result.append(f"{target_color} {prompt}")
            result.append(prompt)
        deduped: List[str] = []
        for prompt in result:
            prompt = self._normalize_prompt(prompt)
            if prompt and prompt not in deduped:
                deduped.append(prompt)
        return deduped[:6]

    def _merge_prompts(self, positive_prompts: List[str], distractor_prompts: List[str]) -> List[str]:
        result: List[str] = []
        for prompt in [*positive_prompts, *distractor_prompts]:
            prompt = self._normalize_prompt(prompt)
            if prompt and prompt not in result:
                result.append(prompt)
        return result[:12]

    def _normalize_prompt(self, prompt: Any) -> str:
        return str(prompt or "").strip().lower()

    def _apply_target_contrast(self, items: List[Evidence], target_en: str) -> None:
        if not target_en:
            return
        distractors = [
            item
            for item in items
            if item.type == "object" and item.bbox and item.attributes.get("target_distractor")
        ]
        if not distractors:
            return
        for item in items:
            if item.type != "object" or not item.bbox or not item.attributes.get("target_match"):
                continue
            best_distractor = None
            best_iou = 0.0
            for distractor in distractors:
                iou = self._bbox_iou(item.bbox, distractor.bbox or [])
                if iou > best_iou:
                    best_iou = iou
                    best_distractor = distractor
            if not best_distractor:
                continue
            comparable = best_distractor.confidence >= max(0.08, item.confidence * 0.35)
            strong_overlap_distractor = best_iou >= 0.55 and best_distractor.confidence >= 0.12
            item_label = self._normalize_prompt(item.label)
            distractor_label = self._normalize_prompt(best_distractor.label)
            if (
                self._normalize_prompt(target_en) == "can"
                and "can" in item_label
                and distractor_label in {"box", "carton", "red box", "red carton", "bottle"}
                and best_distractor.confidence < item.confidence * 1.25
            ):
                continue
            if best_iou >= 0.42 and (comparable or strong_overlap_distractor):
                item.attributes["target_match"] = False
                item.attributes["target_rejected_by"] = best_distractor.label
                item.attributes["target_reject_iou"] = round(best_iou, 3)
                item.attributes["label_zh"] = best_distractor.attributes.get(
                    "label_zh", LABEL_ZH.get(best_distractor.label, best_distractor.label)
                )

    def _dedupe_target_matches(self, items: List[Evidence]) -> None:
        matches = [
            item
            for item in items
            if item.type == "object" and item.bbox and item.attributes.get("target_match")
        ]
        kept: List[Evidence] = []
        for item in sorted(matches, key=lambda evidence: evidence.confidence, reverse=True):
            duplicate_of = None
            for existing in kept:
                if self._bbox_iou(item.bbox or [], existing.bbox or []) >= 0.55:
                    duplicate_of = existing
                    break
            if not duplicate_of:
                kept.append(item)
                continue
            item.attributes["target_match"] = False
            item.attributes["duplicate_of"] = duplicate_of.id
            item.attributes["label_zh"] = item.attributes.get("label_zh") or LABEL_ZH.get(item.label, item.label)

    def _bbox_iou(self, a: List[float], b: List[float]) -> float:
        if len(a) < 4 or len(b) < 4:
            return 0.0
        ax1, ay1, ax2, ay2 = a[:4]
        bx1, by1, bx2, by2 = b[:4]
        inter = self._bbox_intersection_area(a, b)
        if inter <= 0:
            return 0.0
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    def _bbox_area(self, bbox: List[float]) -> float:
        if len(bbox) < 4:
            return 0.0
        x1, y1, x2, y2 = bbox[:4]
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def _overlaps_any_target_box(
        self, bbox: List[float], target_boxes: List[List[float]], threshold: float = 0.30
    ) -> bool:
        area = self._bbox_area(bbox)
        if area <= 0:
            return False
        for target_box in target_boxes:
            target_area = self._bbox_area(target_box)
            if target_area <= 0:
                continue
            inter = self._bbox_intersection_area(bbox, target_box)
            if inter / max(1.0, min(area, target_area)) >= threshold:
                return True
        return False

    def _open_vocab_status_evidence(self, target_en: str, message: str) -> Evidence:
        return Evidence(
            type="tool_status",
            label="open_vocab_unavailable",
            source="yolo_world",
            confidence=0.0,
            timestamp=time.time(),
            ttl=8.0,
            attributes={"target": target_en, "message": message},
        )

    def _yoloe_status_evidence(self, target_en: str, message: str) -> Evidence:
        return Evidence(
            type="tool_status",
            label="yoloe_unavailable",
            source="yoloe",
            confidence=0.0,
            timestamp=time.time(),
            ttl=8.0,
            attributes={"target": target_en, "message": message},
        )

    def _sam3_status_evidence(self, target_en: str, message: str) -> Evidence:
        return Evidence(
            type="tool_status",
            label="sam3_unavailable",
            source="sam3",
            confidence=0.0,
            timestamp=time.time(),
            ttl=8.0,
            attributes={"target": target_en, "message": message},
        )

    def _min_conf_for_label(self, label: str) -> float:
        if label in {"cell phone", "remote", "book"}:
            return 0.48
        if label in {"cup", "wine glass", "bottle", "mouse"}:
            return 0.40
        if label in {"person", "chair", "bed", "couch", "dining table", "backpack", "suitcase"}:
            return 0.38
        return max(0.35, settings.detector_confidence)

    def detect_hands(self, frame: np.ndarray, annotated: np.ndarray) -> Tuple[List[Evidence], np.ndarray]:
        if not settings.enable_hand_tracking:
            return [self._hand_status_evidence("disabled")], annotated
        try:
            hands = self._get_hands()
        except Exception as exc:
            return [self._hand_status_evidence(str(exc))], annotated

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        import mediapipe as mp  # type: ignore

        results = hands.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if not results.hand_landmarks:
            return [], annotated

        items: List[Evidence] = []
        handedness = results.handedness or []
        for index, hand_landmarks in enumerate(results.hand_landmarks):
            points = []
            xs: List[float] = []
            ys: List[float] = []
            for landmark in hand_landmarks:
                px = float(np.clip(landmark.x, 0.0, 1.0) * w)
                py = float(np.clip(landmark.y, 0.0, 1.0) * h)
                xs.append(px)
                ys.append(py)
                points.append(
                    {
                        "x": round(px, 1),
                        "y": round(py, 1),
                        "z": round(float(landmark.z), 4),
                    }
                )
            if not points:
                continue

            pad = 18.0
            x1 = max(0.0, min(xs) - pad)
            y1 = max(0.0, min(ys) - pad)
            x2 = min(float(w), max(xs) + pad)
            y2 = min(float(h), max(ys) + pad)
            position = self._position_from_box((x1, y1, x2, y2), w, h)
            palm_indices = [0, 5, 9, 13, 17]
            palm_center = [
                round(sum(points[i]["x"] for i in palm_indices) / len(palm_indices), 1),
                round(sum(points[i]["y"] for i in palm_indices) / len(palm_indices), 1),
            ]
            index_tip = [points[8]["x"], points[8]["y"]] if len(points) > 8 else palm_center
            gesture = self._classify_hand_gesture(points)

            hand_label = "hand"
            score = 0.7
            if index < len(handedness):
                classification = handedness[index][0]
                hand_label = str(
                    getattr(classification, "category_name", "")
                    or getattr(classification, "display_name", "")
                    or "hand"
                ).lower()
                score = float(getattr(classification, "score", score) or score)
            label_zh = "手"
            if hand_label == "left":
                label_zh = "左手"
            elif hand_label == "right":
                label_zh = "右手"
            motion = self._hand_motion_state(f"{hand_label}:{index}", palm_center, (w, h))
            label_zh = f"{label_zh}-{gesture['label_zh']}"

            item = Evidence(
                type="hand",
                label=hand_label,
                source="mediapipe",
                confidence=round(score, 4),
                timestamp=time.time(),
                ttl=0.7,
                position=position,
                bbox=[round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                attributes={
                    "label_zh": label_zh,
                    "landmarks": points,
                    "index_tip": index_tip,
                    "thumb_tip": [points[4]["x"], points[4]["y"]] if len(points) > 4 else palm_center,
                    "palm_center": palm_center,
                    "frame_size": [w, h],
                    "gesture": gesture["label"],
                    "gesture_zh": gesture["label_zh"],
                    "finger_states": gesture["fingers"],
                    "pinch_distance": gesture["pinch_distance"],
                    "openness": gesture["openness"],
                    "motion": motion,
                },
            )
            items.append(item)
            self._draw_hand(annotated, hand_landmarks, item)
        return items, annotated

    def _get_hands(self) -> Any:
        if self._hands is not None:
            return self._hands
        try:
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core.base_options import BaseOptions

            model_path = self._resolve_optional_path(settings.hand_model_path)
            if not model_path.exists():
                raise FileNotFoundError(f"MediaPipe hand model not found: {model_path}")
            options = vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=2,
                min_hand_detection_confidence=settings.hand_detection_confidence,
                min_hand_presence_confidence=settings.hand_detection_confidence,
                min_tracking_confidence=settings.hand_tracking_confidence,
            )
            self._hands = vision.HandLandmarker.create_from_options(options)
            self._hand_connections = vision.HandLandmarksConnections.HAND_CONNECTIONS
            self._hands_error = ""
            return self._hands
        except Exception as exc:
            self._hands_error = (
                "MediaPipe hand tracker is unavailable. Install mediapipe and make sure "
                f"{self._resolve_optional_path(settings.hand_model_path)} exists. Original error: {repr(exc)[:180]}"
            )
            raise RuntimeError(self._hands_error) from exc

    def _hand_status_evidence(self, message: str) -> Evidence:
        return Evidence(
            type="tool_status",
            label="hand_tracker_unavailable",
            source="mediapipe",
            confidence=0.0,
            timestamp=time.time(),
            ttl=8.0,
            attributes={"message": message},
        )

    def _classify_hand_gesture(self, points: List[Dict[str, float]]) -> Dict[str, Any]:
        if len(points) < 21:
            return {
                "label": "unknown",
                "label_zh": "手势不清",
                "fingers": {},
                "pinch_distance": 1.0,
                "openness": 0.0,
            }

        palm_size = max(
            1.0,
            float(
                np.mean(
                    [
                        self._landmark_distance(points, 0, 5),
                        self._landmark_distance(points, 0, 9),
                        self._landmark_distance(points, 0, 13),
                        self._landmark_distance(points, 0, 17),
                    ]
                )
            ),
        )
        fingers = {
            "thumb": self._finger_extended(points, 4, 3, 2, palm_size, is_thumb=True),
            "index": self._finger_extended(points, 8, 6, 5, palm_size),
            "middle": self._finger_extended(points, 12, 10, 9, palm_size),
            "ring": self._finger_extended(points, 16, 14, 13, palm_size),
            "pinky": self._finger_extended(points, 20, 18, 17, palm_size),
        }
        extended = sum(1 for value in fingers.values() if value)
        pinch_distance = round(self._landmark_distance(points, 4, 8) / palm_size, 3)
        tip_distances = [
            self._point_distance_xy(points[i], self._palm_center_from_points(points)) / palm_size
            for i in (4, 8, 12, 16, 20)
        ]
        openness = round(float(np.mean(tip_distances)), 3)

        if pinch_distance <= 0.42:
            label, label_zh = "pinch", "捏合"
        elif extended >= 4 and openness >= 1.25:
            label, label_zh = "open_palm", "手掌张开"
        elif extended <= 1 and openness <= 1.45:
            label, label_zh = "fist", "握拳/抓取"
        elif fingers["index"] and not any(fingers[name] for name in ("middle", "ring", "pinky")):
            label, label_zh = "pointing", "食指指向"
        elif fingers["index"] and fingers["middle"] and not fingers["ring"] and not fingers["pinky"]:
            label, label_zh = "two_finger", "二指"
        elif extended >= 2:
            label, label_zh = "half_open", "半张开"
        else:
            label, label_zh = "unknown", "手势不清"

        return {
            "label": label,
            "label_zh": label_zh,
            "fingers": fingers,
            "pinch_distance": pinch_distance,
            "openness": openness,
        }

    def _finger_extended(
        self,
        points: List[Dict[str, float]],
        tip_idx: int,
        pip_idx: int,
        mcp_idx: int,
        palm_size: float,
        is_thumb: bool = False,
    ) -> bool:
        wrist = points[0]
        tip = points[tip_idx]
        pip = points[pip_idx]
        mcp = points[mcp_idx]
        tip_from_wrist = self._point_distance_xy(tip, wrist)
        pip_from_wrist = self._point_distance_xy(pip, wrist)
        tip_from_mcp = self._point_distance_xy(tip, mcp)
        pip_from_mcp = self._point_distance_xy(pip, mcp)
        if is_thumb:
            return tip_from_wrist > pip_from_wrist + palm_size * 0.08 and tip_from_mcp > pip_from_mcp * 1.03
        return tip_from_wrist > pip_from_wrist + palm_size * 0.12 and tip_from_mcp > pip_from_mcp * 1.05

    def _landmark_distance(self, points: List[Dict[str, float]], left: int, right: int) -> float:
        return self._point_distance_xy(points[left], points[right])

    def _point_distance_xy(self, left: Dict[str, float], right: Dict[str, float]) -> float:
        return float(((left["x"] - right["x"]) ** 2 + (left["y"] - right["y"]) ** 2) ** 0.5)

    def _palm_center_from_points(self, points: List[Dict[str, float]]) -> Dict[str, float]:
        indices = [0, 5, 9, 13, 17]
        return {
            "x": float(sum(points[i]["x"] for i in indices) / len(indices)),
            "y": float(sum(points[i]["y"] for i in indices) / len(indices)),
        }

    def _hand_motion_state(self, key: str, palm_center: List[float], frame_size: Tuple[int, int]) -> Dict[str, Any]:
        now = time.time()
        previous = self._last_hand_states.get(key)
        self._last_hand_states[key] = {"point": palm_center, "timestamp": now}
        if not previous:
            return {"label": "new", "label_zh": "刚进入画面", "speed": 0.0, "dx": 0.0, "dy": 0.0}

        dt = max(1e-3, now - float(previous.get("timestamp", now)))
        old = previous.get("point") or palm_center
        dx = float(palm_center[0] - old[0])
        dy = float(palm_center[1] - old[1])
        diag = max(1.0, (float(frame_size[0]) ** 2 + float(frame_size[1]) ** 2) ** 0.5)
        speed = ((dx * dx + dy * dy) ** 0.5) / diag / dt
        if speed < 0.06:
            label, label_zh = "steady", "基本稳定"
        elif abs(dx) >= abs(dy):
            label, label_zh = ("moving_right", "向右移动") if dx > 0 else ("moving_left", "向左移动")
        else:
            label, label_zh = ("moving_down", "向下移动") if dy > 0 else ("moving_up", "向上移动")
        return {
            "label": label,
            "label_zh": label_zh,
            "speed": round(float(speed), 3),
            "dx": round(dx, 1),
            "dy": round(dy, 1),
        }

    def _is_hand_person_false_positive(
        self,
        label: str,
        bbox: Tuple[float, float, float, float],
        hand_regions: List[Evidence],
        frame_size: Tuple[int, int],
    ) -> bool:
        if self._normalize_prompt(label) != "person" or not hand_regions:
            return False
        frame_w, frame_h = frame_size
        person_area = max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
        person_ratio = person_area / max(1.0, float(frame_w * frame_h))
        for hand in hand_regions:
            hb = hand.bbox or []
            if len(hb) < 4:
                continue
            hand_area = max(0.0, (hb[2] - hb[0]) * (hb[3] - hb[1]))
            if hand_area <= 0:
                continue
            inter = self._bbox_intersection_area(list(bbox), hb)
            hand_covered = inter / hand_area
            person_covered = inter / max(1.0, person_area)
            hand_center = self._bbox_center(hb)
            center_inside = bbox[0] <= hand_center[0] <= bbox[2] and bbox[1] <= hand_center[1] <= bbox[3]
            if hand_covered >= 0.45 and person_ratio <= 0.58:
                return True
            if center_inside and hand_covered >= 0.15 and person_ratio <= 0.62:
                return True
            if center_inside and person_covered >= 0.12 and person_ratio <= 0.48:
                return True
            expanded = self._expand_bbox(hb, frame_w, frame_h, scale=1.8)
            expanded_area = max(1.0, (expanded[2] - expanded[0]) * (expanded[3] - expanded[1]))
            expanded_overlap = self._bbox_intersection_area(list(bbox), expanded) / min(person_area, expanded_area)
            if expanded_overlap >= 0.38 and person_ratio <= 0.52:
                return True
        return False

    def _expand_bbox(self, bbox: List[float], frame_w: int, frame_h: int, scale: float = 1.5) -> List[float]:
        if len(bbox) < 4:
            return [0.0, 0.0, 0.0, 0.0]
        x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        half_w = max(1.0, (x2 - x1) * scale / 2.0)
        half_h = max(1.0, (y2 - y1) * scale / 2.0)
        return [
            max(0.0, cx - half_w),
            max(0.0, cy - half_h),
            min(float(frame_w), cx + half_w),
            min(float(frame_h), cy + half_h),
        ]

    def _bbox_intersection_area(self, a: List[float], b: List[float]) -> float:
        if len(a) < 4 or len(b) < 4:
            return 0.0
        ix1, iy1 = max(float(a[0]), float(b[0])), max(float(a[1]), float(b[1]))
        ix2, iy2 = min(float(a[2]), float(b[2])), min(float(a[3]), float(b[3]))
        return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)

    def _bbox_center(self, bbox: List[float]) -> Tuple[float, float]:
        if len(bbox) < 4:
            return 0.0, 0.0
        return (float(bbox[0]) + float(bbox[2])) / 2.0, (float(bbox[1]) + float(bbox[3])) / 2.0

    def _draw_hand(self, frame: np.ndarray, hand_landmarks: Any, item: Evidence) -> None:
        h, w = frame.shape[:2]
        points = []
        for landmark in hand_landmarks:
            points.append((int(np.clip(landmark.x, 0.0, 1.0) * w), int(np.clip(landmark.y, 0.0, 1.0) * h)))
        if self._hand_connections is not None:
            for connection in self._hand_connections:
                start = int(getattr(connection, "start", connection[0] if isinstance(connection, (tuple, list)) else 0))
                end = int(getattr(connection, "end", connection[1] if isinstance(connection, (tuple, list)) and len(connection) > 1 else 0))
                if start < len(points) and end < len(points):
                    cv2.line(frame, points[start], points[end], (50, 220, 120), 2)
        for point in points:
            cv2.circle(frame, point, 3, (0, 255, 170), -1)
        self._draw_box(frame, item, color=(30, 220, 120))
        attrs = item.attributes or {}
        gesture = str(attrs.get("gesture_zh") or "")
        motion = attrs.get("motion") or {}
        motion_zh = str(motion.get("label_zh") or "")
        if item.bbox and (gesture or motion_zh):
            x1, y1, _x2, y2 = [int(v) for v in item.bbox]
            cv2.putText(
                frame,
                f"{gesture} {motion_zh}".strip()[:36],
                (x1, min(h - 8, max(24, y2 + 22))),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (30, 220, 120),
                2,
                cv2.LINE_AA,
            )

    def read_text(self, frame: np.ndarray, annotated: np.ndarray) -> Tuple[List[Evidence], np.ndarray, str]:
        try:
            rapid = self._get_rapid_ocr()
            raw, _elapsed = rapid(frame)
            items = self._parse_rapid_ocr(raw, frame.shape)
            for item in items:
                self._draw_box(annotated, item, color=(42, 170, 82))
            if items:
                return items, annotated, "ok:rapidocr"
            if not settings.enable_paddleocr_fallback:
                item = Evidence(
                    type="tool_status",
                    label="no_text_detected",
                    source="rapidocr",
                    confidence=0.0,
                    timestamp=time.time(),
                    ttl=2.0,
                    attributes={"message": "RapidOCR did not find readable text."},
                )
                return [item], annotated, "no_text:rapidocr"
        except Exception:
            if not settings.enable_paddleocr_fallback:
                item = Evidence(
                    type="tool_status",
                    label="ocr_error",
                    source="rapidocr",
                    confidence=0.0,
                    timestamp=time.time(),
                    ttl=4.0,
                    attributes={"message": "RapidOCR failed."},
                )
                return [item], annotated, "error:rapidocr"

        try:
            ocr = self._get_ocr()
            try:
                raw = ocr.predict(frame)
            except AttributeError:
                raw = ocr.ocr(frame)
            items = self._parse_ocr(raw, frame.shape)
            for item in items:
                self._draw_box(annotated, item, color=(42, 170, 82))
            return items, annotated, "ok"
        except Exception as exc:
            item = Evidence(
                type="tool_status",
                label="ocr_error",
                source="paddleocr",
                confidence=0.0,
                timestamp=time.time(),
                ttl=10.0,
                attributes={"error": repr(exc)[:260]},
            )
            return [item], annotated, "error"

    def _parse_rapid_ocr(self, raw: Any, shape: Tuple[int, int, int]) -> List[Evidence]:
        h, w = shape[:2]
        items: List[Evidence] = []
        if not raw:
            return items
        for row in raw[:12]:
            try:
                box, text, score = row
                bbox = self._ocr_box_to_bbox(box)
                position = self._position_from_box(bbox, w, h) if bbox else "unknown"
                items.append(
                    Evidence(
                        type="text",
                        label=str(text),
                        text=str(text),
                        source="rapidocr",
                        confidence=round(float(score), 4),
                        timestamp=time.time(),
                        ttl=6.0,
                        position=position,
                        bbox=bbox,
                    )
                )
            except Exception:
                continue
        return items

    def estimate_depth(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        if not settings.enable_depth:
            return None
        now = time.time()
        if self._last_depth and now - self._last_depth_at < settings.depth_interval:
            return self._last_depth
        if now < self._depth_disabled_until:
            return self._last_depth

        model_path = self._resolve_optional_path(settings.depth_model)
        if not model_path.exists():
            self._depth_error = f"Depth model not found: {model_path}"
            self._depth_disabled_until = now + 60
            return self._last_depth
        if importlib.util.find_spec("depth_anything_3") is None:
            self._depth_error = "depth_anything_3 is not installed"
            self._depth_disabled_until = now + 60
            return self._last_depth

        try:
            model = self._get_depth_model()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            prediction = model.inference(
                [rgb],
                process_res=settings.depth_process_res,
                export_dir=None,
                export_format="mini_npz",
            )
            depth = np.asarray(prediction.depth[0], dtype=np.float32)
            conf = getattr(prediction, "conf", None)
            conf_map = np.asarray(conf[0], dtype=np.float32) if conf is not None else None
            h, w = frame.shape[:2]
            if depth.shape[:2] != (h, w):
                depth = cv2.resize(depth, (w, h), interpolation=cv2.INTER_LINEAR)
            if conf_map is not None and conf_map.shape[:2] != (h, w):
                conf_map = cv2.resize(conf_map, (w, h), interpolation=cv2.INTER_LINEAR)
            valid = depth[np.isfinite(depth)]
            valid = valid[valid > 0]
            if valid.size < 16:
                raise RuntimeError("DA3 returned an empty depth map")
            near = float(np.percentile(valid, 5))
            far = float(np.percentile(valid, 95))
            result = {
                "depth": depth,
                "conf": conf_map,
                "near": near,
                "far": far,
                "timestamp": now,
                "model": str(model_path),
                "source": "da3",
            }
            self._last_depth = result
            self._last_depth_at = now
            self._depth_error = ""
            return result
        except Exception as exc:
            self._depth_error = repr(exc)[:300]
            self._depth_disabled_until = time.time() + 120
            return self._last_depth

    def _attach_depth_to_evidence(
        self, evidence: List[Evidence], depth_result: Dict[str, Any], frame_shape: Tuple[int, int, int]
    ) -> None:
        depth = depth_result.get("depth")
        if depth is None:
            return
        depth = np.asarray(depth, dtype=np.float32)
        conf = depth_result.get("conf")
        conf_map = np.asarray(conf, dtype=np.float32) if conf is not None else None
        near = float(depth_result.get("near") or 0.0)
        far = float(depth_result.get("far") or 0.0)
        if far <= near:
            return
        h, w = frame_shape[:2]
        finite_depth = depth[np.isfinite(depth)]
        for item in evidence:
            if item.type not in {"object", "hand"} or not item.bbox:
                continue
            x1, y1, x2, y2 = self._clamped_bbox(item.bbox, w, h)
            if x2 <= x1 or y2 <= y1:
                continue
            region = depth[y1:y2, x1:x2]
            valid = region[np.isfinite(region)]
            valid = valid[valid > 0]
            if valid.size < 8:
                continue
            median = float(np.median(valid))
            proximity = 1.0 - min(1.0, max(0.0, (median - near) / max(1e-6, far - near)))
            percentile = float((finite_depth <= median).mean()) if finite_depth.size else 0.0
            depth_conf = None
            if conf_map is not None:
                conf_region = conf_map[y1:y2, x1:x2]
                conf_valid = conf_region[np.isfinite(conf_region)]
                if conf_valid.size:
                    depth_conf = float(np.median(conf_valid))
            attrs = item.attributes
            attrs["depth_source"] = str(depth_result.get("source") or "da3")
            attrs["depth_median"] = round(median, 4)
            attrs["depth_proximity"] = round(proximity, 4)
            attrs["depth_percentile_near"] = round(percentile, 4)
            attrs["depth_rank"] = self._depth_rank(proximity)
            if depth_conf is not None:
                attrs["depth_confidence"] = round(depth_conf, 4)

    def _depth_obstacle_evidence(
        self, depth_result: Dict[str, Any], frame_shape: Tuple[int, int, int]
    ) -> Optional[Evidence]:
        depth = depth_result.get("depth")
        if depth is None:
            return None
        depth = np.asarray(depth, dtype=np.float32)
        h, w = frame_shape[:2]
        x1, x2 = int(w * 0.34), int(w * 0.66)
        y1, y2 = int(h * 0.54), int(h * 0.96)
        region = depth[y1:y2, x1:x2]
        valid = region[np.isfinite(region)]
        valid = valid[valid > 0]
        if valid.size < 32:
            return None
        near = float(depth_result.get("near") or 0.0)
        far = float(depth_result.get("far") or 0.0)
        if far <= near:
            return None
        median = float(np.median(valid))
        proximity = 1.0 - min(1.0, max(0.0, (median - near) / max(1e-6, far - near)))
        if proximity < 0.82:
            return None
        return Evidence(
            type="object",
            label="near_obstacle",
            source="da3",
            confidence=round(min(0.78, 0.42 + proximity * 0.38), 4),
            timestamp=time.time(),
            ttl=0.8,
            position=self._position_from_box((x1, y1, x2, y2), w, h),
            bbox=[float(x1), float(y1), float(x2), float(y2)],
            attributes={
                "label_zh": "near obstacle",
                "area_ratio": round((x2 - x1) * (y2 - y1) / float(w * h), 4),
                "depth_source": "da3",
                "depth_median": round(median, 4),
                "depth_proximity": round(proximity, 4),
                "depth_rank": self._depth_rank(proximity),
                "depth_obstacle": True,
            },
        )

    def _depth_result_stats(self, depth_result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "enabled": True,
            "available": True,
            "source": str(depth_result.get("source") or "da3"),
            "model": str(depth_result.get("model") or settings.depth_model),
            "near": round(float(depth_result.get("near") or 0.0), 4),
            "far": round(float(depth_result.get("far") or 0.0), 4),
            "age_ms": round((time.time() - float(depth_result.get("timestamp") or time.time())) * 1000, 1),
        }

    def _depth_rank(self, proximity: float) -> str:
        if proximity >= 0.82:
            return "near"
        if proximity >= 0.55:
            return "mid"
        return "far"

    def _clamped_bbox(self, bbox: List[float], w: int, h: int) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
        return (
            max(0, min(w - 1, int(math.floor(x1)))),
            max(0, min(h - 1, int(math.floor(y1)))),
            max(0, min(w, int(math.ceil(x2)))),
            max(0, min(h, int(math.ceil(y2)))),
        )

    def assess_safety(
        self, evidence: List[Evidence], quality: Dict[str, Any], frame_shape: Tuple[int, int, int]
    ) -> Dict[str, Any]:
        if not quality.get("usable", True):
            return {
                "risk_level": "medium",
                "blocking": True,
                "confidence": 0.58,
                "speech": quality.get("speech") or "画面不可靠，请先停一下。",
                "evidence_ids": [],
            }

        h, w = frame_shape[:2]
        target_boxes = [
            item.bbox
            for item in evidence
            if item.type == "object"
            and item.bbox
            and (
                item.attributes.get("target_match")
                or item.attributes.get("weak_target_match")
                or item.attributes.get("container_surrogate_match")
            )
        ]
        risky: List[Evidence] = []
        caution: List[Evidence] = []
        for item in evidence:
            if item.type != "object" or not item.bbox:
                continue
            if item.confidence < 0.32:
                continue
            if item.attributes.get("depth_obstacle") and self._overlaps_any_target_box(item.bbox, target_boxes):
                continue
            x1, y1, x2, y2 = item.bbox
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            area_ratio = float(item.attributes.get("area_ratio", 0.0))
            center_band = w * 0.28 < cx < w * 0.72
            lower_half = cy > h * 0.42
            bottom_close = y2 > h * 0.86
            large_or_near = area_ratio > 0.22 or (bottom_close and area_ratio > 0.10)
            depth_proximity = float(item.attributes.get("depth_proximity") or 0.0)
            if (
                depth_proximity >= 0.86
                and center_band
                and lower_half
                and not item.attributes.get("target_match")
                and item.confidence >= 0.38
            ):
                risky.append(item)
                continue
            if (
                depth_proximity >= 0.76
                and center_band
                and lower_half
                and not item.attributes.get("target_match")
                and item.confidence >= 0.30
            ):
                caution.append(item)
            if item.label == "person":
                if item.confidence >= 0.6 and center_band and lower_half and area_ratio > 0.25:
                    caution.append(item)
                if item.confidence >= 0.78 and center_band and lower_half and area_ratio > 0.70:
                    risky.append(item)
                continue
            if item.label in RISK_CLASSES and center_band and lower_half and large_or_near and item.confidence >= 0.45:
                risky.append(item)
            elif item.label in RISK_CLASSES and center_band and lower_half and (area_ratio > 0.10 or bottom_close):
                caution.append(item)

        if risky:
            first = risky[0]
            label = str(first.attributes.get("label_zh") or first.label)
            return {
                "risk_level": "high",
                "blocking": True,
                "confidence": max(0.62, first.confidence),
                "speech": f"请先停一下，{first.position}检测到可能靠近的{label}。",
                "evidence_ids": [item.id for item in risky[:4]],
            }

        if caution:
            first = caution[0]
            label = str(first.attributes.get("label_zh") or first.label)
            return {
                "risk_level": "medium",
                "blocking": False,
                "confidence": max(0.52, first.confidence),
                "speech": f"{first.position}检测到{label}，请放慢并继续确认。",
                "evidence_ids": [item.id for item in caution[:4]],
            }

        return {
            "risk_level": "low",
            "blocking": False,
            "confidence": 0.52,
            "speech": "当前画面中没有检测到明显近处障碍。",
            "evidence_ids": [],
        }

    def _parse_ocr(self, raw: Any, shape: Tuple[int, int, int]) -> List[Evidence]:
        h, w = shape[:2]
        items: List[Evidence] = []
        for entry in raw if isinstance(raw, list) else [raw]:
            data = entry
            if hasattr(entry, "json"):
                data = entry.json
            if callable(data):
                data = data()
            if hasattr(entry, "to_dict"):
                data = entry.to_dict()
            if isinstance(data, dict) and "res" in data:
                data = data["res"]

            texts = []
            scores = []
            boxes = []
            if isinstance(data, dict):
                texts = data.get("rec_texts") or data.get("texts") or []
                scores = data.get("rec_scores") or data.get("scores") or []
                boxes = data.get("rec_polys") or data.get("dt_polys") or data.get("boxes") or []
            elif isinstance(data, list):
                for row in data:
                    parsed = self._parse_legacy_ocr_row(row)
                    if parsed:
                        box, text, score = parsed
                        texts.append(text)
                        scores.append(score)
                        boxes.append(box)

            for idx, text in enumerate(texts[:12]):
                if not text:
                    continue
                score = float(scores[idx]) if idx < len(scores) else 0.5
                box = boxes[idx] if idx < len(boxes) else None
                bbox = self._ocr_box_to_bbox(box)
                position = self._position_from_box(bbox, w, h) if bbox else "unknown"
                items.append(
                    Evidence(
                        type="text",
                        label=str(text),
                        text=str(text),
                        source="paddleocr",
                        confidence=round(score, 4),
                        timestamp=time.time(),
                        ttl=6.0,
                        position=position,
                        bbox=bbox,
                    )
                )
        return items

    def _parse_legacy_ocr_row(self, row: Any) -> Optional[Tuple[Any, str, float]]:
        try:
            if isinstance(row, list) and len(row) == 2 and isinstance(row[1], (list, tuple)):
                return row[0], str(row[1][0]), float(row[1][1])
        except Exception:
            return None
        return None

    def _ocr_box_to_bbox(self, box: Any) -> Optional[List[float]]:
        if box is None:
            return None
        arr = np.asarray(box, dtype=float)
        if arr.size < 4:
            return None
        arr = arr.reshape(-1, 2)
        x1, y1 = arr.min(axis=0)
        x2, y2 = arr.max(axis=0)
        return [round(float(x1), 1), round(float(y1), 1), round(float(x2), 1), round(float(y2), 1)]

    def _position_from_box(self, bbox: Tuple[float, float, float, float] | List[float], w: int, h: int) -> str:
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        horiz = "左侧" if cx < w / 3 else "右侧" if cx > w * 2 / 3 else "中间"
        vert = "上方" if cy < h / 3 else "下方" if cy > h * 2 / 3 else "前方"
        if horiz == "中间" and vert == "前方":
            return "正前方"
        return f"{horiz}{vert}"

    def _draw_box(self, frame: np.ndarray, item: Evidence, color: Tuple[int, int, int]) -> None:
        if not item.bbox:
            return
        x1, y1, x2, y2 = [int(v) for v in item.bbox]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{item.label} {item.confidence:.2f}"
        depth_rank = (item.attributes or {}).get("depth_rank")
        if depth_rank:
            label += f" d:{depth_rank}"
        y = max(18, y1 - 8)
        cv2.putText(frame, label[:36], (x1, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

    def _draw_mask(self, frame: np.ndarray, mask: np.ndarray, color: Tuple[int, int, int]) -> None:
        try:
            h, w = frame.shape[:2]
            mask = np.asarray(mask, dtype=np.float32)
            if mask.shape[:2] != (h, w):
                mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)
            mask_bool = mask > 0.45
            if not bool(mask_bool.any()):
                return
            overlay = np.zeros_like(frame)
            overlay[mask_bool] = color
            cv2.addWeighted(overlay, 0.22, frame, 1.0, 0.0, frame)
        except Exception:
            return

    def _clip_cache_status(self) -> Dict[str, Any]:
        cache_path = Path.home() / ".cache" / "clip" / "ViT-B-32.pt"
        if self._clip_checked and (self._clip_cache_ok or time.time() - self._clip_checked_at < 60):
            return {
                "ok": self._clip_cache_ok,
                "message": self._clip_cache_message,
                "path": str(cache_path),
            }

        ok = False
        message = ""
        try:
            import clip  # noqa: F401
        except Exception as exc:
            message = f"openai-clip import failed: {repr(exc)[:220]}"
        else:
            if not cache_path.exists():
                message = f"CLIP ViT-B/32 cache missing at {cache_path}"
            else:
                try:
                    actual_hash = self._sha256_file(cache_path)
                    if actual_hash == CLIP_VIT_B32_SHA256:
                        ok = True
                        message = ""
                    else:
                        message = f"CLIP ViT-B/32 cache checksum mismatch at {cache_path}"
                except Exception as exc:
                    message = f"CLIP ViT-B/32 cache check failed: {repr(exc)[:220]}"

        self._clip_checked = True
        self._clip_checked_at = time.time()
        self._clip_cache_ok = ok
        self._clip_cache_message = message
        return {"ok": ok, "message": message, "path": str(cache_path)}

    def _mobileclip_asset_status(self) -> Dict[str, Any]:
        candidates = [settings.root_dir / "mobileclip_blt.ts", Path("mobileclip_blt.ts").resolve()]
        try:
            from ultralytics.utils import SETTINGS

            weights_dir = Path(SETTINGS.get("weights_dir", ""))
            if str(weights_dir):
                candidates.append(weights_dir / "mobileclip_blt.ts")
        except Exception:
            pass

        unique_candidates: List[Path] = []
        seen = set()
        for candidate in candidates:
            key = str(candidate)
            if key not in seen:
                unique_candidates.append(candidate)
                seen.add(key)

        for candidate in unique_candidates:
            if candidate.exists() and candidate.stat().st_size > 100_000:
                return {"ok": True, "path": str(candidate), "message": ""}

        primary = unique_candidates[0]
        return {
            "ok": False,
            "path": str(primary),
            "message": f"mobileclip_blt.ts is required for YOLOE text prompts; put it at {primary}",
        }

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _get_detector(self) -> Any:
        if self._detector is None:
            with self._lock:
                if self._detector is None:
                    from ultralytics import YOLO

                    self._detector = YOLO(str(settings.root_dir / settings.yolo_model))
        return self._detector

    def _get_yoloe(self) -> Any:
        if self._yoloe is None:
            with self._lock:
                if self._yoloe is None:
                    from ultralytics import YOLOE

                    self._yoloe = YOLOE(str(self._resolve_optional_path(settings.yoloe_model)))
        return self._yoloe

    def _get_world(self) -> Any:
        if self._world is None:
            with self._lock:
                if self._world is None:
                    from ultralytics import YOLO

                    self._world = YOLO(str(settings.root_dir / settings.yolo_world_model))
        return self._world

    def _get_depth_model(self) -> Any:
        if self._depth_model is None:
            with self._lock:
                if self._depth_model is None:
                    import torch
                    from depth_anything_3.api import DepthAnything3

                    model = DepthAnything3.from_pretrained(str(self._resolve_optional_path(settings.depth_model)))
                    device = torch.device("cuda" if self._cuda_available() else "cpu")
                    self._depth_model = model.to(device=device)
        return self._depth_model

    def _get_ocr(self) -> Any:
        if self._ocr is None:
            with self._lock:
                if self._ocr is None:
                    from paddleocr import PaddleOCR

                    self._ocr = PaddleOCR(
                        lang="ch",
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
        return self._ocr

    def _get_rapid_ocr(self) -> Any:
        if self._rapid_ocr is None:
            with self._lock:
                if self._rapid_ocr is None:
                    from rapidocr_onnxruntime import RapidOCR

                    self._rapid_ocr = RapidOCR()
        return self._rapid_ocr

    def _cuda_available(self) -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:
            return False

    def _device(self) -> Any:
        return 0 if self._cuda_available() else "cpu"

    def _torch_device(self) -> str:
        return "cuda:0" if self._cuda_available() else "cpu"

    def _set_world_classes(self, world: Any, classes: Tuple[str, ...]) -> None:
        try:
            world.to(self._torch_device())
        except Exception:
            pass
        world.set_classes(list(classes))
        self._sync_world_text_features(world.model)
        predictor = getattr(world, "predictor", None)
        predictor_model = getattr(predictor, "model", None)
        if predictor_model is not None and predictor_model is not world.model:
            self._sync_world_text_features(predictor_model)

    def _sync_world_text_features(self, model: Any) -> None:
        txt_feats = getattr(model, "txt_feats", None)
        if txt_feats is None or not hasattr(txt_feats, "to"):
            return
        try:
            model_device = next(model.parameters()).device
            if getattr(txt_feats, "device", None) != model_device:
                model.txt_feats = txt_feats.to(model_device)
        except Exception:
            return
