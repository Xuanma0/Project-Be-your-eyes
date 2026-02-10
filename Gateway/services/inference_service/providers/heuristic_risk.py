from __future__ import annotations

import os
from statistics import mean
from typing import Any

from PIL import Image, ImageFilter, ImageStat

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


class HeuristicRiskProvider:
    name = "heuristic"

    def __init__(self) -> None:
        default_model = "heuristic-risk-v1"
        override = str(os.getenv("BYES_SERVICE_RISK_MODEL_ID", "")).strip()
        self.model = override or default_model
        self.target_width = max(96, int(os.getenv("BYES_RISK_TARGET_WIDTH", "320") or "320"))
        self.bottom_ratio = _clamp(float(os.getenv("BYES_RISK_BOTTOM_RATIO", "0.35") or "0.35"), 0.15, 0.60)
        self.center_ratio = _clamp(float(os.getenv("BYES_RISK_CENTER_RATIO", "0.40") or "0.40"), 0.20, 0.70)
        self.edge_threshold = max(1, int(os.getenv("BYES_RISK_EDGE_THRESHOLD", "48") or "48"))
        # v4.20 calibrated defaults (with backward-compatible fallbacks)
        self.obs_warn = _clamp(
            float(
                os.getenv(
                    "BYES_RISK_OBS_WARN",
                    os.getenv("BYES_RISK_EDGE_DENSITY_WARN", "0.14"),
                )
                or "0.14"
            ),
            0.01,
            0.95,
        )
        self.obs_crit = _clamp(
            float(
                os.getenv(
                    "BYES_RISK_OBS_CRIT",
                    os.getenv("BYES_RISK_EDGE_DENSITY_CRIT", "0.24"),
                )
                or "0.24"
            ),
            0.01,
            0.99,
        )
        self.dropoff_peak = _clamp(float(os.getenv("BYES_RISK_DROPOFF_PEAK", "28.0") or "28.0"), 1.0, 255.0)
        self.dropoff_contrast = _clamp(float(os.getenv("BYES_RISK_DROPOFF_CONTRAST", "0.20") or "0.20"), 0.01, 1.0)
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
        self.min_edge_density = _clamp(float(os.getenv("BYES_RISK_MIN_EDGE_DENSITY", "0.02") or "0.02"), 0.0, 1.0)

    def infer(self, image: Image.Image, frame_seq: int | None) -> dict[str, Any]:
        del frame_seq
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
        is_dropoff = dropoff_signal >= self.dropoff_peak and contrast_signal >= self.dropoff_contrast
        is_stair = (
            not is_dropoff
            and dropoff_signal >= self.dropoff_peak * 0.45
            and texture_wave >= 0.015
            and bottom_density >= self.obs_warn * 0.8
        )
        if is_dropoff:
            score = _clamp(max(dropoff_signal / max(self.dropoff_peak * 1.6, 1.0), contrast_signal / self.dropoff_contrast), 0.0, 1.0)
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
                max(dropoff_signal / max(self.dropoff_peak, 1.0), texture_wave / 0.05),
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
            max(bottom_density, center_density) / max(self.obs_crit, 1e-6),
            0.0,
            1.0,
        )
        obstacle_enabled = bottom_density >= self.obs_warn and center_density >= self.obs_warn * 0.9
        if obstacle_enabled and not (unknown_depth_triggered and obstacle_score < 0.95):
            severity = "critical" if obstacle_score >= 1.0 else "warning"
            # avoid duplicate vertical labels unless obstacle is truly critical
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

        hazards = _rank_hazards(hazards)
        # keep only highest-priority vertical hazard to avoid dropoff/stair_down co-existence.
        filtered: list[dict[str, Any]] = []
        seen_vertical = False
        for hazard in hazards:
            kind = str(hazard.get("hazardKind", "")).strip().lower()
            if kind in {"dropoff", "stair_down"}:
                if seen_vertical:
                    continue
                seen_vertical = True
            normalized_kind, _warnings = _normalize_hazard_kind(kind)
            if normalized_kind:
                hazard["hazardKind"] = normalized_kind
            filtered.append(hazard)
        return {"hazards": filtered, "model": self.model}


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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
