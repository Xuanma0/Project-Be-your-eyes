from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from statistics import mean, median
from typing import Any, Mapping

from PIL import Image, ImageFilter, ImageStat

from services.inference_service.providers.depth_base import DepthProvider
from services.inference_service.providers.depth_none import NoneDepthProvider

try:
    from byes.hazards.taxonomy_v1 import normalize_hazard_kind as _normalize_hazard_kind  # type: ignore
except Exception:  # noqa: BLE001
    _LOCAL_ALIAS = {
        "stair_down_edge": "dropoff",
        "drop_off": "dropoff",
        "ledge": "dropoff",
        "cliff": "dropoff",
        "stairs_down": "stair_down",
        "stairs": "stair_down",
        "stairdown": "stair_down",
        "obstacle": "obstacle_close",
        "obstacle_near": "obstacle_close",
    }

    def _normalize_hazard_kind(kind: str) -> tuple[str, list[str]]:
        text = str(kind or "").strip().lower()
        if not text:
            return "", []
        mapped = _LOCAL_ALIAS.get(text, text)
        warnings: list[str] = []
        if mapped != text:
            warnings.append(f"alias:{text}->{mapped}")
        return mapped, warnings


@dataclass(frozen=True)
class RiskThresholds:
    depth_obs_warn: float = 1.0
    depth_obs_crit: float = 0.6
    depth_dropoff_delta: float = 0.8
    obs_warn: float = 0.14
    obs_crit: float = 0.24
    dropoff_peak: float = 28.0
    dropoff_contrast: float = 0.2

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RiskThresholds":
        env = environ if environ is not None else os.environ
        obs_warn_raw = _read_env(env, "BYES_RISK_OBS_WARN") or _read_env(env, "BYES_RISK_EDGE_DENSITY_WARN") or "0.14"
        obs_crit_raw = _read_env(env, "BYES_RISK_OBS_CRIT") or _read_env(env, "BYES_RISK_EDGE_DENSITY_CRIT") or "0.24"
        return cls(
            depth_obs_warn=_clamp(_to_float(_read_env(env, "BYES_RISK_DEPTH_OBS_WARN"), 1.0), 0.01, 20.0),
            depth_obs_crit=_clamp(_to_float(_read_env(env, "BYES_RISK_DEPTH_OBS_CRIT"), 0.6), 0.01, 20.0),
            depth_dropoff_delta=_clamp(_to_float(_read_env(env, "BYES_RISK_DEPTH_DROPOFF_DELTA"), 0.8), 0.05, 20.0),
            obs_warn=_clamp(_to_float(obs_warn_raw, 0.14), 0.01, 0.95),
            obs_crit=_clamp(_to_float(obs_crit_raw, 0.24), 0.01, 0.99),
            dropoff_peak=_clamp(_to_float(_read_env(env, "BYES_RISK_DROPOFF_PEAK"), 28.0), 1.0, 255.0),
            dropoff_contrast=_clamp(_to_float(_read_env(env, "BYES_RISK_DROPOFF_CONTRAST"), 0.2), 0.01, 1.0),
        )

    def with_overrides(self, overrides: Mapping[str, Any] | None) -> "RiskThresholds":
        if not isinstance(overrides, Mapping):
            return self
        return RiskThresholds(
            depth_obs_warn=_clamp(_to_float(_pick_override(overrides, "depth_obs_warn", "depthObsWarn"), self.depth_obs_warn), 0.01, 20.0),
            depth_obs_crit=_clamp(_to_float(_pick_override(overrides, "depth_obs_crit", "depthObsCrit"), self.depth_obs_crit), 0.01, 20.0),
            depth_dropoff_delta=_clamp(
                _to_float(_pick_override(overrides, "depth_dropoff_delta", "depthDropoffDelta"), self.depth_dropoff_delta),
                0.05,
                20.0,
            ),
            obs_warn=_clamp(_to_float(_pick_override(overrides, "obs_warn", "obsWarn"), self.obs_warn), 0.01, 0.95),
            obs_crit=_clamp(_to_float(_pick_override(overrides, "obs_crit", "obsCrit"), self.obs_crit), 0.01, 0.99),
            dropoff_peak=_clamp(_to_float(_pick_override(overrides, "dropoff_peak", "dropoffPeak"), self.dropoff_peak), 1.0, 255.0),
            dropoff_contrast=_clamp(
                _to_float(_pick_override(overrides, "dropoff_contrast", "dropoffContrast"), self.dropoff_contrast),
                0.01,
                1.0,
            ),
        )

    def as_debug_dict(self) -> dict[str, float]:
        return {
            "depthObsWarn": round(self.depth_obs_warn, 6),
            "depthObsCrit": round(self.depth_obs_crit, 6),
            "depthDropoffDelta": round(self.depth_dropoff_delta, 6),
            "obsWarn": round(self.obs_warn, 6),
            "obsCrit": round(self.obs_crit, 6),
            "dropoffPeak": round(self.dropoff_peak, 6),
            "dropoffContrast": round(self.dropoff_contrast, 6),
        }


class HeuristicRiskProvider:
    name = "heuristic"

    def __init__(self, depth_provider: DepthProvider | None = None) -> None:
        self.depth_provider = depth_provider or NoneDepthProvider()
        self.depth_provider_name = str(getattr(self.depth_provider, "name", "none") or "none").strip().lower()
        self.depth_provider_model = str(getattr(self.depth_provider, "model", "none") or "none").strip()
        self.depth_enabled = _env_bool("BYES_RISK_DEPTH_ENABLE", True)

        default_model = "heuristic-risk-v2"
        if self.depth_enabled and self.depth_provider_name not in {"", "none"}:
            depth_model = self.depth_provider_model or self.depth_provider_name
            default_model = f"{default_model}+depth={depth_model}"
        override = str(os.getenv("BYES_SERVICE_RISK_MODEL_ID", "")).strip()
        self.model = override or default_model

        self.target_width = max(96, int(os.getenv("BYES_RISK_TARGET_WIDTH", "320") or "320"))
        self.bottom_ratio = _clamp(float(os.getenv("BYES_RISK_BOTTOM_RATIO", "0.35") or "0.35"), 0.15, 0.60)
        self.center_ratio = _clamp(float(os.getenv("BYES_RISK_CENTER_RATIO", "0.40") or "0.40"), 0.20, 0.70)
        self.edge_threshold = max(1, int(os.getenv("BYES_RISK_EDGE_THRESHOLD", "48") or "48"))

        self.thresholds = RiskThresholds.from_env()
        self.obs_warn = self.thresholds.obs_warn
        self.obs_crit = self.thresholds.obs_crit
        self.dropoff_peak = self.thresholds.dropoff_peak
        self.dropoff_contrast = self.thresholds.dropoff_contrast
        self.min_edge_density = _clamp(float(os.getenv("BYES_RISK_MIN_EDGE_DENSITY", "0.02") or "0.02"), 0.0, 1.0)

        brightness_pair = str(os.getenv("BYES_RISK_UNKNOWN_BRIGHTNESS", "32,222") or "32,222").split(",", 1)
        try:
            b_low = float(brightness_pair[0].strip())
        except Exception:  # noqa: BLE001
            b_low = float(os.getenv("BYES_RISK_BRIGHTNESS_LOW", "32") or "32")
        try:
            b_high = float(brightness_pair[1].strip()) if len(brightness_pair) > 1 else float(
                os.getenv("BYES_RISK_BRIGHTNESS_HIGH", "222") or "222"
            )
        except Exception:  # noqa: BLE001
            b_high = float(os.getenv("BYES_RISK_BRIGHTNESS_HIGH", "222") or "222")
        self.brightness_low = _clamp(b_low, 0.0, 255.0)
        self.brightness_high = _clamp(b_high, 0.0, 255.0)

        self.depth_obs_warn = self.thresholds.depth_obs_warn
        self.depth_obs_crit = self.thresholds.depth_obs_crit
        self.depth_dropoff_delta = self.thresholds.depth_dropoff_delta

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        thresholds_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thresholds = self.thresholds.with_overrides(thresholds_override)
        total_started = time.perf_counter()
        visual_started = time.perf_counter()
        visual_hazards, visual_debug = self._infer_visual_hazards(image, thresholds)
        visual_feature_ms = (time.perf_counter() - visual_started) * 1000.0
        depth_hazards, depth_debug, depth_failed, depth_timings = self._infer_depth_hazards(image, frame_seq, thresholds)

        rule_started = time.perf_counter()
        if depth_hazards:
            hazards = depth_hazards
            source = "depth"
        elif depth_failed:
            hazards = depth_hazards
            source = "depth_error"
        else:
            hazards = visual_hazards
            source = "visual"

        hazards = self._select_primary(hazards)
        filtered: list[dict[str, Any]] = []
        for hazard in hazards:
            kind = str(hazard.get("hazardKind", "")).strip().lower()
            normalized_kind, _warnings = _normalize_hazard_kind(kind)
            if normalized_kind:
                hazard["hazardKind"] = normalized_kind
            filtered.append(hazard)
        rule_ms = (time.perf_counter() - rule_started) * 1000.0

        depth_ms = float(depth_timings.get("depthMs", 0.0))
        feature_ms = visual_feature_ms + float(depth_timings.get("featureMs", 0.0))
        rule_total_ms = rule_ms + float(depth_timings.get("ruleMs", 0.0))
        total_ms = (time.perf_counter() - total_started) * 1000.0

        return {
            "hazards": filtered,
            "model": self.model,
            "debug": {
                "source": source,
                "depth": depth_debug,
                "visual": visual_debug,
                "thresholds": thresholds.as_debug_dict(),
                "timings": {
                    "depthMs": _round_ms(depth_ms),
                    "featureMs": _round_ms(feature_ms),
                    "ruleMs": _round_ms(rule_total_ms),
                    "totalMs": _round_ms(total_ms),
                },
            },
        }

    def _infer_depth_hazards(
        self,
        image: Image.Image,
        frame_seq: int | None,
        thresholds: "RiskThresholds",
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool, dict[str, float]]:
        depth_ms = 0.0
        feature_ms = 0.0
        rule_ms = 0.0

        def _done(hazards: list[dict[str, Any]], failed: bool) -> tuple[list[dict[str, Any]], dict[str, Any], bool, dict[str, float]]:
            return hazards, debug, failed, {
                "depthMs": _round_ms(depth_ms),
                "featureMs": _round_ms(feature_ms),
                "ruleMs": _round_ms(rule_ms),
            }

        debug: dict[str, Any] = {
            "enabled": bool(self.depth_enabled),
            "provider": self.depth_provider_name,
            "model": self.depth_provider_model,
        }
        if not self.depth_enabled or self.depth_provider_name in {"", "none"}:
            return _done([], False)

        depth_started = time.perf_counter()
        try:
            depth_map = self.depth_provider.infer_depth(image, frame_seq)
        except Exception as exc:  # noqa: BLE001
            depth_ms += (time.perf_counter() - depth_started) * 1000.0
            debug["error"] = f"infer_depth_failed:{exc.__class__.__name__}"
            return _done([self._unknown_depth_hazard("depth_infer_failed")], True)
        depth_ms += (time.perf_counter() - depth_started) * 1000.0

        feature_started = time.perf_counter()
        grid = _extract_depth_grid(depth_map)
        feature_ms += (time.perf_counter() - feature_started) * 1000.0
        if not grid:
            debug["error"] = "depth_empty"
            return _done([self._unknown_depth_hazard("depth_empty")], True)

        height = len(grid)
        width = len(grid[0]) if height > 0 else 0
        if width <= 0 or height <= 0:
            debug["error"] = "depth_shape_invalid"
            return _done([self._unknown_depth_hazard("depth_shape_invalid")], True)

        feature_started = time.perf_counter()
        flat = [v for row in grid for v in row if math.isfinite(v) and v > 0.0]
        feature_ms += (time.perf_counter() - feature_started) * 1000.0
        if not flat:
            debug["error"] = "depth_non_finite"
            return _done([self._unknown_depth_hazard("depth_non_finite")], True)

        feature_started = time.perf_counter()
        depth_min = min(flat)
        depth_max = max(flat)
        debug["min"] = round(depth_min, 4)
        debug["max"] = round(depth_max, 4)
        if depth_max - depth_min < 1e-6:
            debug["error"] = "depth_low_dynamic_range"
            feature_ms += (time.perf_counter() - feature_started) * 1000.0
            return _done([self._unknown_depth_hazard("depth_low_dynamic_range")], True)

        bottom_start = max(0, min(height - 1, int(height * (1.0 - self.bottom_ratio))))
        center_left = max(0, int(width * (0.5 - self.center_ratio / 2.0)))
        center_right = min(width, int(width * (0.5 + self.center_ratio / 2.0)))
        if center_right <= center_left:
            center_left = max(0, width // 4)
            center_right = min(width, width - center_left)
        center_bottom = [row[center_left:center_right] for row in grid[bottom_start:]]
        center_values = _flatten_valid(center_bottom)
        if not center_values:
            debug["error"] = "depth_center_empty"
            feature_ms += (time.perf_counter() - feature_started) * 1000.0
            return _done([self._unknown_depth_hazard("depth_center_empty")], True)

        p10 = _percentile(center_values, 0.10)
        local_min = min(center_values)
        debug["roiStats"] = {
            "roi": "bottom_center",
            "depthMin": round(local_min, 4),
            "depthP10": round(p10, 4),
        }

        hazards: list[dict[str, Any]] = []
        obstacle_hazard: dict[str, Any] | None = None
        if local_min <= thresholds.depth_obs_crit:
            score = _clamp(
                (thresholds.depth_obs_crit - local_min) / max(thresholds.depth_obs_crit, 1e-6) + 0.6,
                0.0,
                1.0,
            )
            obstacle_hazard = {
                "hazardKind": "obstacle_close",
                "severity": "critical",
                "score": round(score, 3),
                "evidence": {"roi": "bottom_center", "depthMin": round(local_min, 4), "depthP10": round(p10, 4)},
            }
        elif p10 <= thresholds.depth_obs_warn:
            score = _clamp(
                (thresholds.depth_obs_warn - p10) / max(thresholds.depth_obs_warn, 1e-6) + 0.4,
                0.0,
                1.0,
            )
            obstacle_hazard = {
                "hazardKind": "obstacle_close",
                "severity": "warning",
                "score": round(score, 3),
                "evidence": {"roi": "bottom_center", "depthMin": round(local_min, 4), "depthP10": round(p10, 4)},
            }

        dropoff_hazard: dict[str, Any] | None = None
        bottom_rows = center_bottom
        split_index = max(1, len(bottom_rows) // 2)
        far_values = _flatten_valid(bottom_rows[:split_index])
        near_values = _flatten_valid(bottom_rows[split_index:])
        if far_values and near_values:
            far_med = median(far_values)
            near_med = median(near_values)
            delta = far_med - near_med
            debug["roiStats"]["dropoffDelta"] = round(delta, 4)
            debug["roiStats"]["depthFarMedian"] = round(far_med, 4)
            debug["roiStats"]["depthNearMedian"] = round(near_med, 4)
            if delta >= thresholds.depth_dropoff_delta:
                score = _clamp(delta / max(thresholds.depth_dropoff_delta * 2.0, 1e-6), 0.0, 1.0)
                dropoff_hazard = {
                    "hazardKind": "dropoff",
                    "severity": "critical",
                    "score": round(score, 3),
                    "evidence": {
                        "roi": "bottom",
                        "dropoffDelta": round(delta, 4),
                        "near": round(near_med, 4),
                        "far": round(far_med, 4),
                    },
                }
        feature_ms += (time.perf_counter() - feature_started) * 1000.0

        rule_started = time.perf_counter()
        if dropoff_hazard is not None:
            hazards.append(dropoff_hazard)
        elif obstacle_hazard is not None:
            hazards.append(obstacle_hazard)
        rule_ms += (time.perf_counter() - rule_started) * 1000.0

        return _done(hazards, False)

    def _infer_visual_hazards(
        self,
        image: Image.Image,
        thresholds: "RiskThresholds",
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        resized = _resize_to_width(image, self.target_width).convert("RGB")
        gray = resized.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        width, height = edges.size
        bottom_top = max(0, min(height - 1, int(height * (1.0 - self.bottom_ratio))))
        center_left = max(0, int(width * (0.5 - self.center_ratio / 2.0)))
        center_right = min(width, int(width * (0.5 + self.center_ratio / 2.0)))
        if center_right <= center_left:
            center_left = max(0, width // 4)
            center_right = min(width, width - center_left)

        bottom_edges = edges.crop((0, bottom_top, width, height))
        center_edges = edges.crop((center_left, bottom_top, center_right, height))
        center_gray = gray.crop((center_left, bottom_top, center_right, height))
        bottom_density = _edge_density(bottom_edges, self.edge_threshold)
        center_density = _edge_density(center_edges, self.edge_threshold)
        brightness = float(ImageStat.Stat(gray).mean[0])
        contrast_signal = _bottom_contrast_signal(center_gray)
        dropoff_signal = _dropoff_signal(center_gray)
        texture_wave = _texture_wave_signal(center_edges)

        debug = {
            "brightness": round(brightness, 3),
            "edgeDensityBottom": round(bottom_density, 4),
            "edgeDensityCenter": round(center_density, 4),
            "dropoffSignal": round(dropoff_signal, 4),
            "contrastSignal": round(contrast_signal, 4),
            "textureWave": round(texture_wave, 4),
        }

        hazards: list[dict[str, Any]] = []
        unknown_depth_triggered = (
            brightness <= self.brightness_low or brightness >= self.brightness_high or bottom_density <= self.min_edge_density
        )
        if unknown_depth_triggered:
            exposure_score = max(
                abs(brightness - 127.5) / 127.5,
                0.0 if bottom_density > self.min_edge_density else (self.min_edge_density - bottom_density) * 8.0,
            )
            hazards.append(
                {
                    "hazardKind": "unknown_depth",
                    "severity": "warning",
                    "score": round(_clamp(exposure_score, 0.0, 1.0), 3),
                    "evidence": {
                        "roi": "full",
                        "brightness": round(brightness, 2),
                        "edgeDensityBottom": round(bottom_density, 4),
                    },
                }
            )

        vertical_hazard: dict[str, Any] | None = None
        is_dropoff = dropoff_signal >= thresholds.dropoff_peak and contrast_signal >= thresholds.dropoff_contrast
        is_stair = (
            not is_dropoff
            and dropoff_signal >= thresholds.dropoff_peak * 0.45
            and texture_wave >= 0.015
            and bottom_density >= thresholds.obs_warn * 0.8
        )
        if is_dropoff:
            score = _clamp(
                max(
                    dropoff_signal / max(thresholds.dropoff_peak * 1.6, 1.0),
                    contrast_signal / max(thresholds.dropoff_contrast, 1e-6),
                ),
                0.0,
                1.0,
            )
            vertical_hazard = {
                "hazardKind": "dropoff",
                "severity": "critical",
                "score": round(score, 3),
                "evidence": {
                    "roi": "bottom_center",
                    "edgePeak": round(dropoff_signal, 2),
                    "bottomContrast": round(contrast_signal, 4),
                },
            }
        elif is_stair:
            stair_score = _clamp(
                max(dropoff_signal / max(thresholds.dropoff_peak, 1.0), texture_wave / 0.05),
                0.0,
                1.0,
            )
            vertical_hazard = {
                "hazardKind": "stair_down",
                "severity": "warning" if stair_score < 0.82 else "critical",
                "score": round(stair_score, 3),
                "evidence": {
                    "roi": "bottom_center",
                    "edgePeak": round(dropoff_signal, 2),
                    "textureWave": round(texture_wave, 4),
                },
            }
        if vertical_hazard is not None:
            hazards.append(vertical_hazard)

        obstacle_score = _clamp(
            max(bottom_density, center_density) / max(thresholds.obs_crit, 1e-6),
            0.0,
            1.0,
        )
        obstacle_enabled = bottom_density >= thresholds.obs_warn and center_density >= thresholds.obs_warn * 0.9
        if obstacle_enabled and not (unknown_depth_triggered and obstacle_score < 0.95):
            severity = "critical" if obstacle_score >= 1.0 else "warning"
            if vertical_hazard is None or severity == "critical":
                hazards.append(
                    {
                        "hazardKind": "obstacle_close",
                        "severity": severity,
                        "score": round(obstacle_score, 3),
                        "evidence": {
                            "roi": "bottom_center",
                            "edgeDensityBottom": round(bottom_density, 4),
                            "edgeDensityCenter": round(center_density, 4),
                        },
                    }
                )

        return hazards, debug

    @staticmethod
    def _select_primary(hazards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not hazards:
            return []
        ranked = _rank_hazards(hazards)
        priority = {"dropoff": 0, "stair_down": 1, "obstacle_close": 2, "unknown_depth": 3}
        ranked.sort(
            key=lambda item: (
                priority.get(str(item.get("hazardKind", "")).strip().lower(), 99),
                {"critical": 0, "warning": 1, "info": 2}.get(str(item.get("severity", "warning")).lower(), 3),
                -float(item.get("score", 0.0)),
            )
        )
        return [ranked[0]]

    @staticmethod
    def _unknown_depth_hazard(reason: str) -> dict[str, Any]:
        return {
            "hazardKind": "unknown_depth",
            "severity": "warning",
            "score": 0.55,
            "evidence": {"reason": reason},
        }


def _resize_to_width(image: Image.Image, target_width: int) -> Image.Image:
    width, height = image.size
    if width <= 0 or height <= 0:
        return image
    if width == target_width:
        return image
    ratio = target_width / float(width)
    target_height = max(32, int(round(height * ratio)))
    return image.resize((target_width, target_height), Image.Resampling.BILINEAR)


def _edge_density(image: Image.Image, threshold: int) -> float:
    pixels = image.tobytes()
    if not pixels:
        return 0.0
    strong = 0
    for value in pixels:
        if int(value) >= threshold:
            strong += 1
    return strong / float(len(pixels))


def _dropoff_signal(image: Image.Image) -> float:
    width, height = image.size
    if width <= 0 or height < 6:
        return 0.0
    pixels = image.tobytes()
    rows: list[float] = []
    for y in range(height):
        start = y * width
        end = start + width
        row = pixels[start:end]
        rows.append(mean(float(v) for v in row))
    max_drop = 0.0
    for index in range(len(rows) - 1):
        delta = rows[index] - rows[index + 1]
        if delta > max_drop:
            max_drop = delta
    return max_drop


def _bottom_contrast_signal(image: Image.Image) -> float:
    width, height = image.size
    if width <= 0 or height < 6:
        return 0.0
    pixels = image.tobytes()
    rows: list[float] = []
    for y in range(height):
        start = y * width
        end = start + width
        row = pixels[start:end]
        rows.append(mean(float(v) for v in row))
    max_delta = 0.0
    for index in range(len(rows) - 1):
        delta = abs(rows[index] - rows[index + 1])
        if delta > max_delta:
            max_delta = delta
    return max_delta / 255.0


def _texture_wave_signal(image: Image.Image) -> float:
    width, height = image.size
    if width <= 0 or height < 6:
        return 0.0
    pixels = image.tobytes()
    rows: list[float] = []
    for y in range(height):
        start = y * width
        end = start + width
        row = pixels[start:end]
        rows.append(mean(float(v) for v in row))
    if len(rows) < 3:
        return 0.0
    deltas = [abs(rows[i] - rows[i - 1]) / 255.0 for i in range(1, len(rows))]
    if not deltas:
        return 0.0
    return mean(deltas)


def _rank_hazards(hazards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(
        hazards,
        key=lambda item: (
            order.get(str(item.get("severity", "warning")).lower(), 3),
            -float(item.get("score", 0.0)),
        ),
    )


def _extract_depth_grid(depth_map: Any) -> list[list[float]]:
    if not isinstance(depth_map, dict):
        return []
    raw = depth_map.get("depth")
    if raw is None:
        return []
    if hasattr(raw, "tolist"):
        try:
            raw = raw.tolist()
        except Exception:  # noqa: BLE001
            return []
    if not isinstance(raw, list) or not raw:
        return []

    grid: list[list[float]] = []
    width: int | None = None
    for row in raw:
        if not isinstance(row, list):
            return []
        parsed_row: list[float] = []
        for value in row:
            try:
                parsed_row.append(float(value))
            except Exception:  # noqa: BLE001
                parsed_row.append(float("nan"))
        if width is None:
            width = len(parsed_row)
        if width != len(parsed_row) or width == 0:
            return []
        grid.append(parsed_row)
    return grid


def _flatten_valid(rows: list[list[float]]) -> list[float]:
    out: list[float] = []
    for row in rows:
        for value in row:
            if math.isfinite(value) and value > 0.0:
                out.append(float(value))
    return out


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return min(values)
    if q >= 1:
        return max(values)
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * q))
    index = max(0, min(len(ordered) - 1, index))
    return float(ordered[index])


def _read_env(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    return str(value).strip() if value is not None else ""


def _to_float(value: Any, default: float) -> float:
    if value is None:
        return float(default)
    try:
        text = str(value).strip()
        if not text:
            return float(default)
        return float(text)
    except Exception:  # noqa: BLE001
        return float(default)


def _pick_override(overrides: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in overrides:
            return overrides.get(key)
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_ms(value: float) -> float:
    return round(max(0.0, float(value)), 3)


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}
