from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    data_dir: Path = ROOT_DIR / "data"
    log_dir: Path = ROOT_DIR / "data" / "logs"
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    yolo_model: str = os.getenv("BYE_YOLO_MODEL", "yolo26s.pt").strip()
    base_yolo_mode: str = os.getenv("BYE_BASE_YOLO_MODE", "scene").strip().lower()
    yolo_world_model: str = os.getenv("BYE_YOLO_WORLD_MODEL", "yolov8s-worldv2.pt").strip()
    yoloe_model: str = os.getenv("BYE_YOLOE_MODEL", "yoloe-26s-seg.pt").strip()
    asr_model: str = os.getenv("BYE_ASR_MODEL", "small").strip()
    asr_device: str = os.getenv("BYE_ASR_DEVICE", "auto").strip()
    asr_compute_type: str = os.getenv("BYE_ASR_COMPUTE_TYPE", "auto").strip()
    voice_sidecar_url: str = os.getenv("BYE_VOICE_SIDECAR_URL", "http://127.0.0.1:8010").strip().rstrip("/")
    voice_sidecar_timeout: float = float(os.getenv("BYE_VOICE_SIDECAR_TIMEOUT", "90"))
    tracker_sidecar_url: str = os.getenv("BYE_TRACKER_SIDECAR_URL", "http://127.0.0.1:8020").strip().rstrip("/")
    tracker_sidecar_timeout: float = float(os.getenv("BYE_TRACKER_SIDECAR_TIMEOUT", "12"))
    enable_tracker_sidecar: bool = os.getenv("BYE_ENABLE_TRACKER_SIDECAR", "1").strip() == "1"
    enable_yoloe: bool = os.getenv("BYE_ENABLE_YOLOE", "1").strip() == "1"
    enable_yolo_world: bool = os.getenv("BYE_ENABLE_YOLO_WORLD", "1").strip() == "1"
    enable_sam3: bool = os.getenv("BYE_ENABLE_SAM3", "1").strip() == "1"
    sam3_model: str = os.getenv("BYE_SAM3_MODEL", "sam3.pt").strip()
    sam3_confidence: float = float(os.getenv("BYE_SAM3_CONF", "0.22"))
    enable_deepseek_tool_planner: bool = os.getenv("BYE_DEEPSEEK_TOOL_PLANNER", "0").strip() == "1"
    enable_paddleocr_fallback: bool = os.getenv("BYE_ENABLE_PADDLEOCR_FALLBACK", "0").strip() == "1"
    camera_index: int = int(os.getenv("BYE_CAMERA_INDEX", "0"))
    camera_width: int = int(os.getenv("BYE_CAMERA_WIDTH", "1280"))
    camera_height: int = int(os.getenv("BYE_CAMERA_HEIGHT", "720"))
    camera_fps: int = int(os.getenv("BYE_CAMERA_FPS", "30"))
    stream_width: int = int(os.getenv("BYE_STREAM_WIDTH", "640"))
    stream_fps: float = float(os.getenv("BYE_STREAM_FPS", "15"))
    detector_confidence: float = float(os.getenv("BYE_DETECTOR_CONF", "0.25"))
    yoloe_confidence: float = float(os.getenv("BYE_YOLOE_CONF", "0.12"))
    yolo_world_confidence: float = float(os.getenv("BYE_YOLO_WORLD_CONF", "0.12"))
    enable_hand_tracking: bool = os.getenv("BYE_ENABLE_HAND_TRACKING", "1").strip() == "1"
    hand_model_path: str = os.getenv("BYE_HAND_MODEL", str(ROOT_DIR / "data" / "models" / "hand_landmarker.task")).strip()
    hand_detection_confidence: float = float(os.getenv("BYE_HAND_DETECT_CONF", "0.45"))
    hand_tracking_confidence: float = float(os.getenv("BYE_HAND_TRACK_CONF", "0.45"))
    enable_depth: bool = os.getenv("BYE_ENABLE_DEPTH", "1").strip() == "1"
    depth_model: str = os.getenv("BYE_DEPTH_MODEL", "models/DA3-SMALL").strip()
    depth_process_res: int = int(os.getenv("BYE_DEPTH_PROCESS_RES", "392"))
    depth_interval: float = float(os.getenv("BYE_DEPTH_INTERVAL", "2.5"))
    evidence_max_items: int = int(os.getenv("BYE_EVIDENCE_MAX_ITEMS", "240"))


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.log_dir.mkdir(parents=True, exist_ok=True)
