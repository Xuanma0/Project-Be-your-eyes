from __future__ import annotations

import os
from dataclasses import dataclass


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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class GatewayConfig:
    send_envelope: bool
    default_ttl_ms: int
    risk_priority: int
    perception_priority: int
    navigation_priority: int
    dialog_priority: int
    health_priority: int
    low_confidence_threshold: float
    fast_lane_deadline_ms: int
    slow_lane_deadline_ms: int
    fast_q_maxsize: int
    slow_q_maxsize: int
    slow_q_drop_threshold: int
    timeout_rate_threshold: float
    timeout_window_size: int
    safe_mode_without_ws_client: bool
    ws_disconnect_grace_ms: int
    ws_no_client_warn_interval_ms: int
    mock_risk_delay_ms: int
    mock_risk_confidence: float
    mock_risk_distance_m: float
    mock_risk_azimuth_deg: float
    mock_risk_text: str
    mock_ocr_delay_ms: int
    mock_ocr_confidence: float
    mock_ocr_text: str
    mock_tool_timeout_ms: int
    frame_tracker_retention_ms: int = 120000
    frame_tracker_max_entries: int = 20000
    enable_real_det: bool = False
    real_det_endpoint: str = "http://127.0.0.1:9001/infer"
    real_det_timeout_ms: int = 600
    real_det_p95_budget_ms: int = 450
    real_det_max_inflight: int = 2
    real_det_queue_policy: str = "drop"
    real_det_min_interval_ms: int = 300
    real_det_cache_max_age_ms: int = 3000
    enable_real_ocr: bool = False
    real_ocr_endpoint: str = "http://127.0.0.1:9102/infer/ocr"
    real_ocr_timeout_ms: int = 900
    real_ocr_p95_budget_ms: int = 750
    real_ocr_max_inflight: int = 1
    real_ocr_queue_policy: str = "drop"
    real_ocr_min_interval_ms: int = 500
    real_ocr_cache_max_age_ms: int = 1500
    enable_real_depth: bool = False
    real_depth_endpoint: str = "http://127.0.0.1:8012/infer"
    real_depth_timeout_ms: int = 800
    real_depth_p95_budget_ms: int = 700
    real_depth_max_inflight: int = 1
    real_depth_queue_policy: str = "drop"
    real_depth_sample_every_n_frames: int = 5
    real_depth_cache_max_age_ms: int = 1800
    real_depth_hazard_distance_threshold_m: float = 1.5
    real_depth_hazard_azimuth_threshold_deg: float = 30.0
    crosscheck_depth_far_threshold_m: float = 3.0
    crosscheck_depth_near_threshold_m: float = 1.5
    crosscheck_det_low_conf_threshold: float = 0.45
    crosscheck_cooldown_ms: int = 8000
    crosscheck_transparent_aliases_csv: str = "door,glass door,glass,window,mirror,barrier"
    hazard_memory_grace_ms: int = 2500
    hazard_memory_emit_cooldown_ms: int = 1800
    hazard_memory_critical_dist_m: float = 1.0
    hazard_memory_max_active: int = 64
    hazard_memory_decay_ms: int = 12000
    det_max_side: int = 640
    ocr_max_side: int = 1280
    depth_max_side: int = 640
    det_jpeg_quality: int = 75
    ocr_jpeg_quality: int = 80
    depth_jpeg_quality: int = 75
    critical_tools_csv: str = "mock_risk"
    enabled_tools_csv: str = ""
    tool_cache_max_entries: int = 1024
    planner_recent_window: int = 8
    fast_budget_ms: int = 500
    slow_budget_ms: int = 1200


def load_config() -> GatewayConfig:
    slow_q_maxsize = _env_int("BYES_SLOW_Q_MAXSIZE", 64)
    return GatewayConfig(
        send_envelope=_env_bool("GATEWAY_SEND_ENVELOPE", False),
        default_ttl_ms=_env_int("BYES_DEFAULT_TTL_MS", 3000),
        risk_priority=_env_int("BYES_RISK_PRIORITY", 100),
        perception_priority=_env_int("BYES_PERCEPTION_PRIORITY", 10),
        navigation_priority=_env_int("BYES_NAV_PRIORITY", 20),
        dialog_priority=_env_int("BYES_DIALOG_PRIORITY", 30),
        health_priority=_env_int("BYES_HEALTH_PRIORITY", 90),
        low_confidence_threshold=_env_float("BYES_LOW_CONF_THRESHOLD", 0.6),
        fast_lane_deadline_ms=_env_int("BYES_FAST_DEADLINE_MS", 500),
        slow_lane_deadline_ms=_env_int("BYES_SLOW_DEADLINE_MS", 1800),
        fast_q_maxsize=_env_int("BYES_FAST_Q_MAXSIZE", 128),
        slow_q_maxsize=slow_q_maxsize,
        slow_q_drop_threshold=_env_int("BYES_SLOW_Q_DROP_THRESHOLD", slow_q_maxsize),
        timeout_rate_threshold=_env_float("BYES_TIMEOUT_RATE_THRESHOLD", 0.35),
        timeout_window_size=_env_int("BYES_TIMEOUT_WINDOW_SIZE", 50),
        safe_mode_without_ws_client=_env_bool("BYES_SAFE_MODE_NO_WS", True),
        ws_disconnect_grace_ms=_env_int("BYES_WS_DISCONNECT_GRACE_MS", 3000),
        ws_no_client_warn_interval_ms=_env_int("BYES_WS_NO_CLIENT_WARN_INTERVAL_MS", 5000),
        mock_risk_delay_ms=_env_int("BYES_MOCK_RISK_DELAY_MS", 120),
        mock_risk_confidence=_env_float("BYES_MOCK_RISK_CONFIDENCE", 0.92),
        mock_risk_distance_m=_env_float("BYES_MOCK_RISK_DISTANCE_M", 1.5),
        mock_risk_azimuth_deg=_env_float("BYES_MOCK_RISK_AZIMUTH_DEG", 0.0),
        mock_risk_text=os.getenv("BYES_MOCK_RISK_TEXT", "Obstacle ahead"),
        mock_ocr_delay_ms=_env_int("BYES_MOCK_OCR_DELAY_MS", 200),
        mock_ocr_confidence=_env_float("BYES_MOCK_OCR_CONFIDENCE", 0.8),
        mock_ocr_text=os.getenv("BYES_MOCK_OCR_TEXT", "Door detected"),
        mock_tool_timeout_ms=_env_int("BYES_MOCK_TOOL_TIMEOUT_MS", 1200),
        frame_tracker_retention_ms=_env_int("BYES_FRAME_TRACKER_RETENTION_MS", 120000),
        frame_tracker_max_entries=_env_int("BYES_FRAME_TRACKER_MAX_ENTRIES", 20000),
        enable_real_det=_env_bool("BYES_ENABLE_REAL_DET", False),
        real_det_endpoint=os.getenv("BYES_REAL_DET_ENDPOINT", "http://127.0.0.1:9001/infer"),
        real_det_timeout_ms=_env_int("BYES_REAL_DET_TIMEOUT_MS", 600),
        real_det_p95_budget_ms=_env_int("BYES_REAL_DET_P95_BUDGET_MS", 450),
        real_det_max_inflight=_env_int("BYES_REAL_DET_MAX_INFLIGHT", 2),
        real_det_queue_policy=os.getenv("BYES_REAL_DET_QUEUE_POLICY", "drop"),
        real_det_min_interval_ms=_env_int("BYES_REAL_DET_MIN_INTERVAL_MS", 300),
        real_det_cache_max_age_ms=_env_int("BYES_REAL_DET_CACHE_MAX_AGE_MS", 3000),
        enable_real_ocr=_env_bool("BYES_ENABLE_REAL_OCR", False),
        real_ocr_endpoint=os.getenv("BYES_REAL_OCR_ENDPOINT", "http://127.0.0.1:9102/infer/ocr"),
        real_ocr_timeout_ms=_env_int("BYES_REAL_OCR_TIMEOUT_MS", 900),
        real_ocr_p95_budget_ms=_env_int("BYES_REAL_OCR_P95_BUDGET_MS", 750),
        real_ocr_max_inflight=_env_int("BYES_REAL_OCR_MAX_INFLIGHT", 1),
        real_ocr_queue_policy=os.getenv("BYES_REAL_OCR_QUEUE_POLICY", "drop"),
        real_ocr_min_interval_ms=_env_int("BYES_REAL_OCR_MIN_INTERVAL_MS", 500),
        real_ocr_cache_max_age_ms=_env_int("BYES_REAL_OCR_CACHE_MAX_AGE_MS", 1500),
        enable_real_depth=_env_bool("BYES_ENABLE_REAL_DEPTH", False),
        real_depth_endpoint=os.getenv("BYES_REAL_DEPTH_ENDPOINT", "http://127.0.0.1:8012/infer"),
        real_depth_timeout_ms=_env_int("BYES_REAL_DEPTH_TIMEOUT_MS", 800),
        real_depth_p95_budget_ms=_env_int("BYES_REAL_DEPTH_P95_BUDGET_MS", 700),
        real_depth_max_inflight=_env_int("BYES_REAL_DEPTH_MAX_INFLIGHT", 1),
        real_depth_queue_policy=os.getenv("BYES_REAL_DEPTH_QUEUE_POLICY", "drop"),
        real_depth_sample_every_n_frames=_env_int("BYES_REAL_DEPTH_SAMPLE_EVERY_N_FRAMES", 5),
        real_depth_cache_max_age_ms=_env_int("BYES_REAL_DEPTH_CACHE_MAX_AGE_MS", 1800),
        real_depth_hazard_distance_threshold_m=_env_float("BYES_REAL_DEPTH_HAZARD_DISTANCE_M", 1.5),
        real_depth_hazard_azimuth_threshold_deg=_env_float("BYES_REAL_DEPTH_HAZARD_AZIMUTH_DEG", 30.0),
        crosscheck_depth_far_threshold_m=_env_float("BYES_CROSSCHECK_DEPTH_FAR_THRESHOLD_M", 3.0),
        crosscheck_depth_near_threshold_m=_env_float("BYES_CROSSCHECK_DEPTH_NEAR_THRESHOLD_M", 1.5),
        crosscheck_det_low_conf_threshold=_env_float("BYES_CROSSCHECK_DET_LOW_CONF", 0.45),
        crosscheck_cooldown_ms=_env_int("BYES_CROSSCHECK_COOLDOWN_MS", 8000),
        crosscheck_transparent_aliases_csv=os.getenv(
            "BYES_CROSSCHECK_TRANSPARENT_ALIASES",
            "door,glass door,glass,window,mirror,barrier",
        ),
        hazard_memory_grace_ms=_env_int("BYES_HAZARD_GRACE_MS", 2500),
        hazard_memory_emit_cooldown_ms=_env_int("BYES_HAZARD_EMIT_COOLDOWN_MS", 1800),
        hazard_memory_critical_dist_m=_env_float("BYES_HAZARD_CRITICAL_DIST_M", 1.0),
        hazard_memory_max_active=_env_int("BYES_HAZARD_MAX_ACTIVE", 64),
        hazard_memory_decay_ms=_env_int("BYES_HAZARD_DECAY_MS", 12000),
        det_max_side=_env_int("BYES_DET_MAX_SIDE", 640),
        ocr_max_side=_env_int("BYES_OCR_MAX_SIDE", 1280),
        depth_max_side=_env_int("BYES_DEPTH_MAX_SIDE", 640),
        det_jpeg_quality=_env_int("BYES_DET_JPEG_QUALITY", 75),
        ocr_jpeg_quality=_env_int("BYES_OCR_JPEG_QUALITY", 80),
        depth_jpeg_quality=_env_int("BYES_DEPTH_JPEG_QUALITY", 75),
        critical_tools_csv=os.getenv("BYES_CRITICAL_TOOLS", "mock_risk"),
        enabled_tools_csv=os.getenv("BYES_ENABLED_TOOLS", ""),
        tool_cache_max_entries=_env_int("BYES_TOOL_CACHE_MAX_ENTRIES", 1024),
        planner_recent_window=_env_int("BYES_PLANNER_RECENT_WINDOW", 8),
        fast_budget_ms=_env_int("BYES_FAST_BUDGET_MS", 500),
        slow_budget_ms=_env_int("BYES_SLOW_BUDGET_MS", 1200),
    )
