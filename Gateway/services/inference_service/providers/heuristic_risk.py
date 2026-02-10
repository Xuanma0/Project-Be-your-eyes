from __future__ import annotations

import os
from statistics import mean
from typing import Any

from PIL import Image, ImageFilter, ImageStat


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
        self.edge_warn = _clamp(float(os.getenv("BYES_RISK_EDGE_DENSITY_WARN", "0.095") or "0.095"), 0.01, 0.90)
        self.edge_crit = _clamp(float(os.getenv("BYES_RISK_EDGE_DENSITY_CRIT", "0.145") or "0.145"), 0.01, 0.95)
        self.contrast_warn = _clamp(float(os.getenv("BYES_RISK_BOTTOM_CONTRAST_WARN", "0.16") or "0.16"), 0.01, 1.0)
        self.contrast_crit = _clamp(float(os.getenv("BYES_RISK_BOTTOM_CONTRAST_CRIT", "0.28") or "0.28"), 0.01, 1.0)
        self.dropoff_peak = _clamp(float(os.getenv("BYES_RISK_DROPOFF_PEAK", "24.0") or "24.0"), 1.0, 255.0)
        self.brightness_low = _clamp(float(os.getenv("BYES_RISK_BRIGHTNESS_LOW", "32") or "32"), 0.0, 255.0)
        self.brightness_high = _clamp(float(os.getenv("BYES_RISK_BRIGHTNESS_HIGH", "222") or "222"), 0.0, 255.0)
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

        hazards: list[dict[str, Any]] = []
        if brightness <= self.brightness_low or brightness >= self.brightness_high or bottom_density <= self.min_edge_density:
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

        if (
            (bottom_density >= self.edge_warn and center_density >= self.edge_warn * 0.8)
            or contrast_signal >= self.contrast_warn
        ):
            severity = "critical" if (
                bottom_density >= self.edge_crit or center_density >= self.edge_crit or contrast_signal >= self.contrast_crit
            ) else "warning"
            edge_score = max(bottom_density, center_density) / max(self.edge_crit, 1e-6)
            contrast_score = contrast_signal / max(self.contrast_crit, 1e-6)
            score = _clamp(max(edge_score, contrast_score), 0.0, 1.0)
            hazards.append(
                {
                    "hazardKind": "obstacle_close",
                    "severity": severity,
                    "score": round(score, 3),
                    "evidence": {
                        "roi": "bottom_center",
                        "edgeDensityBottom": round(bottom_density, 4),
                        "edgeDensityCenter": round(center_density, 4),
                        "bottomContrast": round(contrast_signal, 4),
                    },
                }
            )

        if dropoff_signal >= self.dropoff_peak:
            score = _clamp(dropoff_signal / max(self.dropoff_peak * 2.0, 1.0), 0.0, 1.0)
            hazards.append(
                {
                    "hazardKind": "stair_down",
                    "severity": "critical",
                    "score": round(score, 3),
                    "evidence": {
                        "roi": "bottom_center",
                        "edgePeak": round(dropoff_signal, 2),
                    },
                }
            )

        return {"hazards": _rank_hazards(hazards), "model": self.model}


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
    upper = rows[: max(1, height // 2)]
    lower = rows[-max(1, height // 2) :]
    return abs(mean(upper) - mean(lower)) / 255.0


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
