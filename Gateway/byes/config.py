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
    )
