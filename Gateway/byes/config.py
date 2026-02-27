from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


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


def _env_string_list(csv_name: str, json_name: str) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()

    raw_json = str(os.getenv(json_name, "")).strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, list):
                for item in parsed:
                    text = str(item or "").strip()
                    normalized = text.lower()
                    if text and normalized not in seen:
                        seen.add(normalized)
                        values.append(text)
        except Exception:
            pass

    raw_csv = str(os.getenv(csv_name, "")).strip()
    if raw_csv:
        for item in raw_csv.split(","):
            text = str(item or "").strip()
            normalized = text.lower()
            if text and normalized not in seen:
                seen.add(normalized)
                values.append(text)

    return tuple(values)


def _env_seg_prompt() -> dict[str, Any] | None:
    raw_json = str(os.getenv("BYES_SEG_PROMPT_JSON", "")).strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    prompt: dict[str, Any] = {}

    raw_targets_json = str(os.getenv("BYES_SEG_PROMPT_TARGETS_JSON", "")).strip()
    if raw_targets_json:
        try:
            parsed = json.loads(raw_targets_json)
            if isinstance(parsed, list):
                targets: list[str] = []
                seen: set[str] = set()
                for item in parsed:
                    text = str(item or "").strip()
                    key = text.lower()
                    if text and key not in seen:
                        seen.add(key)
                        targets.append(text)
                if targets:
                    prompt["targets"] = targets
        except Exception:
            pass

    raw_targets_csv = str(os.getenv("BYES_SEG_PROMPT_TARGETS", "")).strip()
    if raw_targets_csv:
        existing = prompt.get("targets")
        merged: list[str] = [str(item).strip() for item in existing if str(item).strip()] if isinstance(existing, list) else []
        seen = {item.lower() for item in merged}
        for item in raw_targets_csv.split(","):
            text = str(item or "").strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                merged.append(text)
        if merged:
            prompt["targets"] = merged

    raw_boxes_json = str(os.getenv("BYES_SEG_PROMPT_BOXES_JSON", "")).strip()
    if raw_boxes_json:
        try:
            parsed = json.loads(raw_boxes_json)
            if isinstance(parsed, list):
                boxes: list[list[float]] = []
                for item in parsed:
                    if not isinstance(item, list) or len(item) != 4:
                        continue
                    try:
                        boxes.append([float(item[0]), float(item[1]), float(item[2]), float(item[3])])
                    except Exception:
                        continue
                if boxes:
                    prompt["boxes"] = boxes
        except Exception:
            pass

    raw_points_json = str(os.getenv("BYES_SEG_PROMPT_POINTS_JSON", "")).strip()
    if raw_points_json:
        try:
            parsed = json.loads(raw_points_json)
            if isinstance(parsed, list):
                points: list[dict[str, float | int]] = []
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    try:
                        x = float(item.get("x"))
                        y = float(item.get("y"))
                        label = int(item.get("label"))
                    except Exception:
                        continue
                    if label not in {0, 1}:
                        continue
                    points.append({"x": x, "y": y, "label": label})
                if points:
                    prompt["points"] = points
        except Exception:
            pass

    raw_version = str(os.getenv("BYES_SEG_PROMPT_VERSION", "")).strip()
    if raw_version:
        meta = prompt.get("meta")
        meta_obj = dict(meta) if isinstance(meta, dict) else {}
        meta_obj["promptVersion"] = raw_version
        prompt["meta"] = meta_obj

    raw_text = str(os.getenv("BYES_SEG_PROMPT_TEXT", "")).strip()
    if raw_text:
        prompt["text"] = raw_text

    return prompt or None


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
    gateway_profile: str = "local"
    gateway_dev_endpoints_enabled: bool = True
    gateway_runpackage_upload_enabled: bool = True
    gateway_allow_local_runpackage_path: bool = True
    gateway_max_frame_bytes: int = 0
    gateway_max_runpackage_zip_bytes: int = 0
    gateway_max_json_bytes: int = 0
    gateway_rate_limit_enabled: bool = False
    gateway_rate_limit_rps: float = 10.0
    gateway_rate_limit_burst: int = 20
    gateway_rate_limit_key_mode: str = "ip"
    mode_profile_json: str = ""
    emit_mode_profile_debug: bool = False
    emit_net_debug: bool = False
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
    real_vlm_url: str = ""
    real_vlm_timeout_ms: int = 1800
    real_vlm_max_inflight: int = 1
    real_vlm_queue_policy: str = "drop_newest"
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
    planner_v1_enabled: bool = True
    world_state_retention_ms: int = 30000
    world_state_max_sessions: int = 64
    planner_det_stale_ms: int = 1500
    planner_depth_stale_ms: int = 1200
    planner_ocr_stale_ms: int = 3000
    planner_vlm_stale_ms: int = 3000
    planner_crosscheck_force_ms: int = 4000
    planner_crosscheck_cooldown_ms: int = 2500
    planner_ask_guidance_cooldown_ms: int = 5000
    planner_text_object_aliases_csv: str = "sign,label,screen,panel,text"
    confirm_default_ttl_ms: int = 5000
    confirm_dedup_cooldown_ms: int = 4000
    confirm_yes_ttl_ms: int = 5000
    confirm_no_suppress_ms: int = 8000
    fast_budget_ms: int = 500
    slow_budget_ms: int = 1200
    slo_e2e_p95_ms: int = 400
    slo_preproc_p95_ms: int = 80
    slo_queue_depth_threshold: int = 24
    slo_timeout_rate_threshold: float = 0.35
    slo_window_size: int = 50
    slo_recover_ticks: int = 3
    throttled_det_every_n_frames: int = 3
    throttled_ocr_every_n_frames: int = 4
    throttled_depth_every_n_frames: int = 1
    preempt_window_ms: int = 1500
    critical_latch_ms: int = 1500
    critical_near_m: float = 1.0
    critical_from_crosscheck_kinds_csv: str = "vision_without_depth,depth_without_vision,transparent_obstacle,dropoff"
    inference_enable_ocr: bool = False
    inference_enable_risk: bool = True
    inference_enable_seg: bool = False
    inference_enable_depth: bool = False
    inference_enable_slam: bool = False
    inference_enable_costmap: bool = False
    inference_enable_costmap_fused: bool = False
    inference_ocr_backend: str = "mock"
    inference_risk_backend: str = "mock"
    inference_seg_backend: str = "mock"
    inference_depth_backend: str = "mock"
    inference_slam_backend: str = "mock"
    inference_ocr_http_url: str = "http://127.0.0.1:9001/ocr"
    inference_risk_http_url: str = "http://127.0.0.1:9002/risk"
    inference_seg_http_url: str = "http://127.0.0.1:9003/seg"
    inference_depth_http_url: str = "http://127.0.0.1:9004/depth"
    inference_slam_http_url: str = "http://127.0.0.1:9005/slam/pose"
    inference_seg_targets: tuple[str, ...] = ()
    inference_seg_prompt: dict[str, Any] | None = None
    inference_seg_tracking: bool = False
    inference_seg_prompt_max_chars: int = 256
    inference_seg_prompt_max_targets: int = 8
    inference_seg_prompt_max_boxes: int = 4
    inference_seg_prompt_max_points: int = 8
    inference_seg_prompt_budget_mode: str = "targets_text_boxes_points"
    inference_ocr_timeout_ms: int = 1500
    inference_risk_timeout_ms: int = 1200
    inference_seg_timeout_ms: int = 1200
    inference_depth_timeout_ms: int = 1200
    inference_slam_timeout_ms: int = 1200
    inference_ocr_model_id: str = "mock-ocr"
    inference_risk_model_id: str = "mock-risk"
    inference_seg_model_id: str = "mock-seg"
    inference_depth_model_id: str = "mock-depth"
    inference_slam_model_id: str = "mock-slam"
    inference_depth_http_ref_view_strategy: str = ""
    inference_depth_temporal_roi: str = "bottom_center"
    inference_depth_temporal_near_thresh_m: float = 1.0
    inference_depth_temporal_require_same_size: bool = True
    inference_slam_traj_preferred: str = "auto"
    inference_slam_traj_allowed: tuple[str, ...] = ("online", "final")
    inference_costmap_grid_h: int = 32
    inference_costmap_grid_w: int = 32
    inference_costmap_resolution_m: float = 0.1
    inference_costmap_depth_thresh_m: float = 1.0
    inference_costmap_dynamic_labels: tuple[str, ...] = ("person", "car")
    inference_costmap_dynamic_track: bool = False
    inference_costmap_dynamic_track_ttl_frames: int = 5
    inference_costmap_fused_alpha: float = 0.6
    inference_costmap_fused_decay: float = 0.95
    inference_costmap_fused_window: int = 10
    inference_costmap_fused_shift: bool = True
    inference_costmap_fused_shift_gate: bool = True
    inference_costmap_fused_min_tracking_rate: float = 0.6
    inference_costmap_fused_max_lost_streak: int = 2
    inference_costmap_fused_max_align_residual_p90_ms: int = 80
    inference_costmap_fused_max_ate_rmse_m: float = 0.25
    inference_costmap_fused_max_rpe_trans_rmse_m: float = 0.1
    inference_costmap_occupied_thresh: int = 200
    inference_costmap_context_max_chars: int = 512
    inference_costmap_context_mode: str = "topk_hotspots"
    inference_costmap_context_source: str = "auto"
    inference_emit_ws_events_v1: bool = False
    inference_event_component: str = "gateway"


def load_config() -> GatewayConfig:
    slow_q_maxsize = _env_int("BYES_SLOW_Q_MAXSIZE", 64)
    return GatewayConfig(
        gateway_profile=(str(os.getenv("BYES_GATEWAY_PROFILE", "local")).strip().lower() or "local"),
        gateway_dev_endpoints_enabled=_env_bool("BYES_GATEWAY_DEV_ENDPOINTS_ENABLED", True),
        gateway_runpackage_upload_enabled=_env_bool("BYES_GATEWAY_RUNPACKAGE_UPLOAD_ENABLED", True),
        gateway_allow_local_runpackage_path=_env_bool("BYES_GATEWAY_ALLOW_LOCAL_RUNPACKAGE_PATH", True),
        gateway_max_frame_bytes=max(0, _env_int("BYES_GATEWAY_MAX_FRAME_BYTES", 0)),
        gateway_max_runpackage_zip_bytes=max(0, _env_int("BYES_GATEWAY_MAX_RUNPACKAGE_ZIP_BYTES", 0)),
        gateway_max_json_bytes=max(0, _env_int("BYES_GATEWAY_MAX_JSON_BYTES", 0)),
        gateway_rate_limit_enabled=_env_bool("BYES_GATEWAY_RATE_LIMIT_ENABLED", False),
        gateway_rate_limit_rps=max(0.1, _env_float("BYES_GATEWAY_RATE_LIMIT_RPS", 10.0)),
        gateway_rate_limit_burst=max(1, _env_int("BYES_GATEWAY_RATE_LIMIT_BURST", 20)),
        gateway_rate_limit_key_mode=(
            str(os.getenv("BYES_GATEWAY_RATE_LIMIT_KEY_MODE", "ip")).strip().lower() or "ip"
        ),
        mode_profile_json=str(os.getenv("BYES_MODE_PROFILE_JSON", "") or ""),
        emit_mode_profile_debug=_env_bool("BYES_EMIT_MODE_PROFILE_DEBUG", False),
        emit_net_debug=_env_bool("BYES_EMIT_NET_DEBUG", False),
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
        real_vlm_url=os.getenv("BYES_REAL_VLM_URL", ""),
        real_vlm_timeout_ms=_env_int("BYES_REAL_VLM_TIMEOUT_MS", 1800),
        real_vlm_max_inflight=_env_int("BYES_REAL_VLM_MAX_INFLIGHT", 1),
        real_vlm_queue_policy=os.getenv("BYES_REAL_VLM_QUEUE_POLICY", "drop_newest"),
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
        planner_v1_enabled=_env_bool("BYES_PLANNER_V1_ENABLED", True),
        world_state_retention_ms=_env_int("BYES_WORLD_STATE_RETENTION_MS", 30000),
        world_state_max_sessions=_env_int("BYES_WORLD_STATE_MAX_SESSIONS", 64),
        planner_det_stale_ms=_env_int("BYES_PLANNER_DET_STALE_MS", 1500),
        planner_depth_stale_ms=_env_int("BYES_PLANNER_DEPTH_STALE_MS", 1200),
        planner_ocr_stale_ms=_env_int("BYES_PLANNER_OCR_STALE_MS", 3000),
        planner_vlm_stale_ms=_env_int("BYES_PLANNER_VLM_STALE_MS", 3000),
        planner_crosscheck_force_ms=_env_int("BYES_PLANNER_CROSSCHECK_FORCE_MS", 4000),
        planner_crosscheck_cooldown_ms=_env_int("BYES_PLANNER_CROSSCHECK_COOLDOWN_MS", 2500),
        planner_ask_guidance_cooldown_ms=_env_int("BYES_PLANNER_ASK_GUIDANCE_COOLDOWN_MS", 5000),
        planner_text_object_aliases_csv=os.getenv(
            "BYES_PLANNER_TEXT_OBJECT_ALIASES",
            "sign,label,screen,panel,text",
        ),
        confirm_default_ttl_ms=_env_int("BYES_CONFIRM_DEFAULT_TTL_MS", 5000),
        confirm_dedup_cooldown_ms=_env_int("BYES_CONFIRM_DEDUP_COOLDOWN_MS", 4000),
        confirm_yes_ttl_ms=_env_int("BYES_CONFIRM_YES_TTL_MS", 5000),
        confirm_no_suppress_ms=_env_int("BYES_CONFIRM_NO_SUPPRESS_MS", 8000),
        fast_budget_ms=_env_int("BYES_FAST_BUDGET_MS", 500),
        slow_budget_ms=_env_int("BYES_SLOW_BUDGET_MS", 1200),
        slo_e2e_p95_ms=_env_int("BYES_SLO_E2E_P95_MS", 400),
        slo_preproc_p95_ms=_env_int("BYES_SLO_PREPROC_P95_MS", 80),
        slo_queue_depth_threshold=_env_int("BYES_SLO_QUEUE_DEPTH_THRESHOLD", 24),
        slo_timeout_rate_threshold=_env_float("BYES_SLO_TIMEOUT_RATE_THRESHOLD", 0.35),
        slo_window_size=_env_int("BYES_SLO_WINDOW_SIZE", 50),
        slo_recover_ticks=_env_int("BYES_SLO_RECOVER_TICKS", 3),
        throttled_det_every_n_frames=_env_int("BYES_THROTTLED_DET_EVERY_N_FRAMES", 3),
        throttled_ocr_every_n_frames=_env_int("BYES_THROTTLED_OCR_EVERY_N_FRAMES", 4),
        throttled_depth_every_n_frames=_env_int("BYES_THROTTLED_DEPTH_EVERY_N_FRAMES", 1),
        preempt_window_ms=_env_int("BYES_PREEMPT_WINDOW_MS", 1500),
        critical_latch_ms=_env_int("BYES_CRITICAL_LATCH_MS", 1500),
        critical_near_m=_env_float("BYES_CRITICAL_NEAR_M", 1.0),
        critical_from_crosscheck_kinds_csv=os.getenv(
            "BYES_CRITICAL_FROM_CROSSCHECK_KINDS",
            "vision_without_depth,depth_without_vision,transparent_obstacle,dropoff",
        ),
        inference_enable_ocr=_env_bool("BYES_ENABLE_OCR", False),
        inference_enable_risk=_env_bool("BYES_ENABLE_RISK", True),
        inference_enable_seg=_env_bool("BYES_ENABLE_SEG", False),
        inference_enable_depth=_env_bool("BYES_ENABLE_DEPTH", False),
        inference_enable_slam=_env_bool("BYES_ENABLE_SLAM", False),
        inference_enable_costmap=_env_bool("BYES_ENABLE_COSTMAP", False),
        inference_enable_costmap_fused=_env_bool("BYES_ENABLE_COSTMAP_FUSED", False),
        inference_ocr_backend=os.getenv("BYES_OCR_BACKEND", os.getenv("BYES_SERVICE_OCR_PROVIDER", "mock")),
        inference_risk_backend=os.getenv("BYES_RISK_BACKEND", "mock"),
        inference_seg_backend=os.getenv("BYES_SEG_BACKEND", "mock"),
        inference_depth_backend=os.getenv("BYES_DEPTH_BACKEND", "mock"),
        inference_slam_backend=os.getenv("BYES_SLAM_BACKEND", "mock"),
        inference_ocr_http_url=os.getenv(
            "BYES_OCR_HTTP_URL",
            os.getenv("BYES_SERVICE_OCR_ENDPOINT", "http://127.0.0.1:9001/ocr"),
        ),
        inference_risk_http_url=os.getenv("BYES_RISK_HTTP_URL", "http://127.0.0.1:9002/risk"),
        inference_seg_http_url=os.getenv("BYES_SEG_HTTP_URL", "http://127.0.0.1:9003/seg"),
        inference_depth_http_url=os.getenv("BYES_DEPTH_HTTP_URL", "http://127.0.0.1:9004/depth"),
        inference_slam_http_url=os.getenv("BYES_SLAM_HTTP_URL", "http://127.0.0.1:9005/slam/pose"),
        inference_seg_targets=_env_string_list("BYES_SEG_TARGETS", "BYES_SEG_TARGETS_JSON"),
        inference_seg_prompt=_env_seg_prompt(),
        inference_seg_tracking=_env_bool("BYES_SEG_TRACKING", False),
        inference_seg_prompt_max_chars=_env_int("BYES_SEG_PROMPT_MAX_CHARS", 256),
        inference_seg_prompt_max_targets=_env_int("BYES_SEG_PROMPT_MAX_TARGETS", 8),
        inference_seg_prompt_max_boxes=_env_int("BYES_SEG_PROMPT_MAX_BOXES", 4),
        inference_seg_prompt_max_points=_env_int("BYES_SEG_PROMPT_MAX_POINTS", 8),
        inference_seg_prompt_budget_mode=(
            str(os.getenv("BYES_SEG_PROMPT_BUDGET_MODE", "targets_text_boxes_points")).strip()
            or "targets_text_boxes_points"
        ),
        inference_ocr_timeout_ms=_env_int(
            "BYES_OCR_HTTP_TIMEOUT_MS",
            _env_int("BYES_SERVICE_OCR_TIMEOUT_MS", 1500),
        ),
        inference_risk_timeout_ms=_env_int("BYES_RISK_HTTP_TIMEOUT_MS", 1200),
        inference_seg_timeout_ms=_env_int("BYES_SEG_HTTP_TIMEOUT_MS", 1200),
        inference_depth_timeout_ms=_env_int("BYES_DEPTH_HTTP_TIMEOUT_MS", 1200),
        inference_slam_timeout_ms=_env_int(
            "BYES_SLAM_HTTP_TIMEOUT_MS",
            _env_int("BYES_SERVICE_SLAM_TIMEOUT_MS", 1200),
        ),
        inference_ocr_model_id=os.getenv("BYES_OCR_MODEL_ID", os.getenv("BYES_SERVICE_OCR_MODEL_ID", "mock-ocr")),
        inference_risk_model_id=os.getenv("BYES_RISK_MODEL_ID", "mock-risk"),
        inference_seg_model_id=os.getenv("BYES_SEG_MODEL_ID", "mock-seg"),
        inference_depth_model_id=os.getenv("BYES_DEPTH_MODEL_ID", "mock-depth"),
        inference_slam_model_id=os.getenv("BYES_SLAM_MODEL_ID", os.getenv("BYES_SERVICE_SLAM_MODEL_ID", "mock-slam")),
        inference_depth_http_ref_view_strategy=(
            str(
                os.getenv(
                    "BYES_DEPTH_HTTP_REF_VIEW_STRATEGY",
                    os.getenv("BYES_SERVICE_DEPTH_HTTP_REF_VIEW_STRATEGY", ""),
                )
            ).strip()
        ),
        inference_depth_temporal_roi=(
            str(os.getenv("BYES_DEPTH_TEMPORAL_ROI", "bottom_center")).strip().lower() or "bottom_center"
        ),
        inference_depth_temporal_near_thresh_m=_env_float("BYES_DEPTH_TEMPORAL_NEAR_THRESH_M", 1.0),
        inference_depth_temporal_require_same_size=_env_bool("BYES_DEPTH_TEMPORAL_REQUIRE_SAME_SIZE", True),
        inference_slam_traj_preferred=(str(os.getenv("BYES_SLAM_TRAJ_PREFERRED", "auto")).strip().lower() or "auto"),
        inference_slam_traj_allowed=(
            _env_string_list("BYES_SLAM_TRAJ_ALLOWED", "BYES_SLAM_TRAJ_ALLOWED_JSON")
            or ("online", "final")
        ),
        inference_costmap_grid_h=_env_int("BYES_COSTMAP_GRID_H", 32),
        inference_costmap_grid_w=_env_int("BYES_COSTMAP_GRID_W", 32),
        inference_costmap_resolution_m=_env_float("BYES_COSTMAP_RES_M", 0.1),
        inference_costmap_depth_thresh_m=_env_float("BYES_COSTMAP_DEPTH_THRESH_M", 1.0),
        inference_costmap_dynamic_labels=(
            _env_string_list("BYES_COSTMAP_DYNAMIC_LABELS", "BYES_COSTMAP_DYNAMIC_LABELS_JSON")
            or ("person", "car")
        ),
        inference_costmap_dynamic_track=_env_bool("BYES_ENABLE_COSTMAP_DYNAMIC_TRACK", False),
        inference_costmap_dynamic_track_ttl_frames=_env_int("BYES_COSTMAP_DYNAMIC_TRACK_TTL_FRAMES", 5),
        inference_costmap_fused_alpha=_env_float("BYES_COSTMAP_FUSED_ALPHA", 0.6),
        inference_costmap_fused_decay=_env_float("BYES_COSTMAP_FUSED_DECAY", 0.95),
        inference_costmap_fused_window=_env_int("BYES_COSTMAP_FUSED_WINDOW", 10),
        inference_costmap_fused_shift=_env_bool("BYES_COSTMAP_FUSED_SHIFT", True),
        inference_costmap_fused_shift_gate=_env_bool("BYES_COSTMAP_FUSED_SHIFT_GATE", True),
        inference_costmap_fused_min_tracking_rate=_env_float("BYES_COSTMAP_FUSED_MIN_TRACKING_RATE", 0.6),
        inference_costmap_fused_max_lost_streak=_env_int("BYES_COSTMAP_FUSED_MAX_LOST_STREAK", 2),
        inference_costmap_fused_max_align_residual_p90_ms=_env_int(
            "BYES_COSTMAP_FUSED_MAX_ALIGN_RESIDUAL_P90_MS",
            80,
        ),
        inference_costmap_fused_max_ate_rmse_m=_env_float("BYES_COSTMAP_FUSED_MAX_ATE_RMSE_M", 0.25),
        inference_costmap_fused_max_rpe_trans_rmse_m=_env_float("BYES_COSTMAP_FUSED_MAX_RPE_TRANS_RMSE_M", 0.1),
        inference_costmap_occupied_thresh=_env_int("BYES_COSTMAP_OCCUPIED_THRESH", 200),
        inference_costmap_context_max_chars=_env_int("BYES_COSTMAP_CONTEXT_MAX_CHARS", 512),
        inference_costmap_context_mode=(
            str(os.getenv("BYES_COSTMAP_CONTEXT_MODE", "topk_hotspots")).strip()
            or "topk_hotspots"
        ),
        inference_costmap_context_source=(
            str(os.getenv("BYES_COSTMAP_CONTEXT_SOURCE", "auto")).strip().lower() or "auto"
        ),
        inference_emit_ws_events_v1=_env_bool("BYES_INFERENCE_EMIT_WS_V1", False),
        inference_event_component=os.getenv("BYES_INFERENCE_EVENT_COMPONENT", "gateway"),
    )
