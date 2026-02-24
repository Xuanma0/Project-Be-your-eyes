from __future__ import annotations

import math
from typing import Any

DEFAULT_PROMPT_BUDGET = {
    "maxChars": 256,
    "maxTargets": 8,
    "maxBoxes": 4,
    "maxPoints": 8,
    "mode": "targets_text_boxes_points",
}

_MODE_ALIASES = {
    "targets": "targets",
    "target": "targets",
    "text": "text",
    "boxes": "boxes",
    "box": "boxes",
    "points": "points",
    "point": "points",
}


def normalize_prompt(prompt: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(prompt, dict):
        return None
    out: dict[str, Any] = {}

    targets_raw = prompt.get("targets")
    if isinstance(targets_raw, list):
        targets: list[str] = []
        seen: set[str] = set()
        for item in targets_raw:
            text = str(item or "").strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                targets.append(text)
        if targets:
            out["targets"] = targets

    text_raw = str(prompt.get("text", "")).strip()
    if text_raw:
        out["text"] = text_raw

    boxes_raw = prompt.get("boxes")
    if isinstance(boxes_raw, list):
        boxes: list[list[float]] = []
        for row in boxes_raw:
            if not isinstance(row, list) or len(row) != 4:
                continue
            try:
                boxes.append([float(row[0]), float(row[1]), float(row[2]), float(row[3])])
            except Exception:
                continue
        if boxes:
            out["boxes"] = boxes

    points_raw = prompt.get("points")
    if isinstance(points_raw, list):
        points: list[dict[str, float | int]] = []
        for row in points_raw:
            if not isinstance(row, dict):
                continue
            try:
                x = float(row.get("x"))
                y = float(row.get("y"))
                label = int(row.get("label"))
            except Exception:
                continue
            if label not in {0, 1}:
                continue
            points.append({"x": x, "y": y, "label": label})
        if points:
            out["points"] = points

    for key in ("imageWidth", "imageHeight"):
        value = prompt.get(key)
        try:
            parsed = int(value)
        except Exception:
            continue
        if parsed > 0:
            out[key] = parsed

    meta_raw = prompt.get("meta")
    if isinstance(meta_raw, dict):
        raw_version = meta_raw.get("promptVersion")
        prompt_version = "" if raw_version is None else str(raw_version).strip()
        if prompt_version:
            out["meta"] = {"promptVersion": prompt_version}

    schema_version = str(prompt.get("schemaVersion", "")).strip()
    if schema_version:
        out["schemaVersion"] = schema_version

    return out or None


def normalize_budget(budget: dict[str, Any] | None) -> dict[str, Any]:
    src = budget if isinstance(budget, dict) else {}
    out = dict(DEFAULT_PROMPT_BUDGET)
    out["maxChars"] = _to_nonnegative_int(src.get("maxChars"), DEFAULT_PROMPT_BUDGET["maxChars"])
    out["maxTargets"] = _to_nonnegative_int(src.get("maxTargets"), DEFAULT_PROMPT_BUDGET["maxTargets"])
    out["maxBoxes"] = _to_nonnegative_int(src.get("maxBoxes"), DEFAULT_PROMPT_BUDGET["maxBoxes"])
    out["maxPoints"] = _to_nonnegative_int(src.get("maxPoints"), DEFAULT_PROMPT_BUDGET["maxPoints"])
    out["mode"] = _normalize_mode(src.get("mode"))
    return out


def pack_prompt(
    prompt: dict[str, Any] | None,
    *,
    budget: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    normalized = normalize_prompt(prompt)
    normalized_budget = normalize_budget(budget)
    in_stats = _prompt_stats_in(normalized)

    if normalized is None:
        empty_stats = {
            "in": in_stats,
            "out": {"targets": 0, "textChars": 0, "boxes": 0, "points": 0, "charsTotal": 0, "tokenApprox": 0},
            "truncation": {"targetsDropped": 0, "boxesDropped": 0, "pointsDropped": 0, "textCharsDropped": 0},
            "complexity": {"hasText": False, "hasBoxes": False, "hasPoints": False, "hasTargets": False, "score": 0.0},
            "warningsCount": 0,
            "packed": False,
        }
        return None, empty_stats

    working: dict[str, Any] = dict(normalized)
    truncation = {
        "targetsDropped": 0,
        "boxesDropped": 0,
        "pointsDropped": 0,
        "textCharsDropped": 0,
    }

    targets = list(working.get("targets", [])) if isinstance(working.get("targets"), list) else []
    max_targets = int(normalized_budget["maxTargets"])
    if len(targets) > max_targets:
        truncation["targetsDropped"] = len(targets) - max_targets
        targets = targets[:max_targets]
    if targets:
        working["targets"] = targets
    else:
        working.pop("targets", None)

    boxes = list(working.get("boxes", [])) if isinstance(working.get("boxes"), list) else []
    max_boxes = int(normalized_budget["maxBoxes"])
    if len(boxes) > max_boxes:
        truncation["boxesDropped"] = len(boxes) - max_boxes
        boxes = boxes[:max_boxes]
    if boxes:
        working["boxes"] = boxes
    else:
        working.pop("boxes", None)

    points = list(working.get("points", [])) if isinstance(working.get("points"), list) else []
    max_points = int(normalized_budget["maxPoints"])
    if len(points) > max_points:
        truncation["pointsDropped"] = len(points) - max_points
        points = points[:max_points]
    if points:
        working["points"] = points
    else:
        working.pop("points", None)

    text = str(working.get("text", "") or "")
    text_max = int(normalized_budget["maxChars"])
    if len(text) > text_max:
        truncation["textCharsDropped"] = len(text) - text_max
        text = text[:text_max]
    if text:
        working["text"] = text
    else:
        working.pop("text", None)

    # Secondary budget pass: keep preferred modalities first when char budget is tight.
    mode_order = _mode_tokens(str(normalized_budget["mode"]))
    char_budget = int(normalized_budget["maxChars"])
    chars_left = char_budget
    kept: dict[str, Any] = {}
    if "schemaVersion" in working:
        kept["schemaVersion"] = working["schemaVersion"]
    if "meta" in working:
        kept["meta"] = dict(working["meta"]) if isinstance(working.get("meta"), dict) else working["meta"]
    for key in ("imageWidth", "imageHeight"):
        if key in working:
            kept[key] = working[key]

    payload_parts = {
        "targets": list(working.get("targets", [])) if isinstance(working.get("targets"), list) else [],
        "text": str(working.get("text", "") or ""),
        "boxes": list(working.get("boxes", [])) if isinstance(working.get("boxes"), list) else [],
        "points": list(working.get("points", [])) if isinstance(working.get("points"), list) else [],
    }

    for part in mode_order:
        if part == "targets":
            values = payload_parts["targets"]
            if not values:
                continue
            item_chars = sum(len(str(v)) for v in values)
            if item_chars <= chars_left:
                kept["targets"] = values
                chars_left -= item_chars
            else:
                allowed: list[str] = []
                for item in values:
                    item_text = str(item)
                    if len(item_text) <= chars_left:
                        allowed.append(item_text)
                        chars_left -= len(item_text)
                    else:
                        truncation["targetsDropped"] += 1
                if allowed:
                    kept["targets"] = allowed
        elif part == "text":
            value = payload_parts["text"]
            if not value:
                continue
            if len(value) <= chars_left:
                kept["text"] = value
                chars_left -= len(value)
            else:
                kept["text"] = value[:chars_left]
                truncation["textCharsDropped"] += max(0, len(value) - chars_left)
                chars_left = 0
        elif part == "boxes":
            values = payload_parts["boxes"]
            if not values:
                continue
            encoded_items = [_estimate_box_chars(v) for v in values]
            allowed: list[list[float]] = []
            for idx, cost in enumerate(encoded_items):
                if cost <= chars_left:
                    allowed.append(values[idx])
                    chars_left -= cost
                else:
                    truncation["boxesDropped"] += 1
            if allowed:
                kept["boxes"] = allowed
        elif part == "points":
            values = payload_parts["points"]
            if not values:
                continue
            encoded_items = [_estimate_point_chars(v) for v in values]
            allowed: list[dict[str, float | int]] = []
            for idx, cost in enumerate(encoded_items):
                if cost <= chars_left:
                    allowed.append(values[idx])
                    chars_left -= cost
                else:
                    truncation["pointsDropped"] += 1
            if allowed:
                kept["points"] = allowed

    packed_prompt = kept if any(key in kept for key in ("targets", "text", "boxes", "points")) else None

    out_targets = len(kept.get("targets", [])) if isinstance(kept.get("targets"), list) else 0
    out_text_chars = len(str(kept.get("text", "") or ""))
    out_boxes = len(kept.get("boxes", [])) if isinstance(kept.get("boxes"), list) else 0
    out_points = len(kept.get("points", [])) if isinstance(kept.get("points"), list) else 0
    out_chars_total = (
        sum(len(str(item)) for item in (kept.get("targets", []) if isinstance(kept.get("targets"), list) else []))
        + out_text_chars
        + sum(_estimate_box_chars(item) for item in (kept.get("boxes", []) if isinstance(kept.get("boxes"), list) else []))
        + sum(
            _estimate_point_chars(item) for item in (kept.get("points", []) if isinstance(kept.get("points"), list) else [])
        )
    )
    out_token_approx = int(math.ceil(float(out_chars_total) / 4.0)) if out_chars_total > 0 else 0

    warnings_count = int(
        truncation["targetsDropped"] > 0
        or truncation["boxesDropped"] > 0
        or truncation["pointsDropped"] > 0
        or truncation["textCharsDropped"] > 0
    )
    complexity = {
        "hasText": out_text_chars > 0,
        "hasBoxes": out_boxes > 0,
        "hasPoints": out_points > 0,
        "hasTargets": out_targets > 0,
        "score": float(
            (2.0 if out_text_chars > 0 else 0.0)
            + (1.0 if out_targets > 0 else 0.0)
            + (1.5 if out_boxes > 0 else 0.0)
            + (1.5 if out_points > 0 else 0.0)
        ),
    }

    stats = {
        "in": in_stats,
        "out": {
            "targets": out_targets,
            "textChars": out_text_chars,
            "boxes": out_boxes,
            "points": out_points,
            "charsTotal": out_chars_total,
            "tokenApprox": out_token_approx,
        },
        "truncation": truncation,
        "complexity": complexity,
        "warningsCount": warnings_count,
        "packed": True,
    }
    return packed_prompt, stats


def _prompt_stats_in(prompt: dict[str, Any] | None) -> dict[str, int]:
    targets_count = len(prompt.get("targets", [])) if isinstance(prompt, dict) and isinstance(prompt.get("targets"), list) else 0
    boxes_count = len(prompt.get("boxes", [])) if isinstance(prompt, dict) and isinstance(prompt.get("boxes"), list) else 0
    points_count = len(prompt.get("points", [])) if isinstance(prompt, dict) and isinstance(prompt.get("points"), list) else 0
    text_chars = len(str(prompt.get("text", "") or "")) if isinstance(prompt, dict) else 0
    return {
        "targets": targets_count,
        "textChars": text_chars,
        "boxes": boxes_count,
        "points": points_count,
    }


def _to_nonnegative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return int(default)
    return max(0, parsed)


def _normalize_mode(raw_mode: Any) -> str:
    text = str(raw_mode or "").strip().lower()
    if not text:
        return str(DEFAULT_PROMPT_BUDGET["mode"])
    tokens = _mode_tokens(text)
    if not tokens:
        return str(DEFAULT_PROMPT_BUDGET["mode"])
    return "_".join(tokens)


def _mode_tokens(mode: str) -> list[str]:
    parts: list[str] = []
    seen: set[str] = set()
    for token in str(mode or "").replace(",", "_").split("_"):
        normalized = _MODE_ALIASES.get(token.strip().lower(), "")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        parts.append(normalized)
    for token in ("targets", "text", "boxes", "points"):
        if token not in seen:
            parts.append(token)
    return parts


def _estimate_box_chars(value: Any) -> int:
    if isinstance(value, list):
        return len(",".join(str(float(v)) for v in value))
    return len(str(value))


def _estimate_point_chars(value: Any) -> int:
    if isinstance(value, dict):
        return len(f"{value.get('x', '')},{value.get('y', '')},{value.get('label', '')}")
    return len(str(value))
