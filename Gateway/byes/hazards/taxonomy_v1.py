from __future__ import annotations

from typing import Any

CANONICAL_KINDS: set[str] = {
    "dropoff",
    "stair_down",
    "obstacle_close",
    "unknown_depth",
    "low_clearance",
}

ALIASES: dict[str, str] = {
    "stair_down_edge": "dropoff",
    "drop_off": "dropoff",
    "ledge": "dropoff",
    "cliff": "dropoff",
    "stairs_down": "stair_down",
    "stairs": "stair_down",
    "stairdown": "stair_down",
    "obstacle": "obstacle_close",
    "obstacle_near": "obstacle_close",
    "unknown": "unknown_depth",
}


def normalize_hazard_kind(kind: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    text = str(kind or "").strip().lower()
    if not text:
        return "", warnings
    mapped = ALIASES.get(text, text)
    if mapped != text:
        warnings.append(f"alias:{text}->{mapped}")
    if mapped not in CANONICAL_KINDS:
        warnings.append(f"unknown_kind:{mapped}")
    return mapped, warnings


def normalize_hazards(hazards: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in hazards:
        if not isinstance(item, dict):
            continue
        original_kind = (
            str(item.get("hazardKind") or item.get("kind") or item.get("type") or "").strip()
        )
        normalized_kind, kind_warnings = normalize_hazard_kind(original_kind)
        warnings.extend(kind_warnings)
        if not normalized_kind:
            continue
        severity = str(item.get("severity", "warning")).strip().lower()
        if severity not in {"critical", "warning", "info"}:
            severity = "warning"
        row: dict[str, Any] = {"hazardKind": normalized_kind, "severity": severity}
        if original_kind and normalized_kind != original_kind.lower():
            row["originalKind"] = original_kind
        if "score" in item:
            try:
                row["score"] = float(item["score"])
            except Exception:  # noqa: BLE001
                pass
        evidence = item.get("evidence")
        if isinstance(evidence, dict):
            row["evidence"] = dict(evidence)
        rows.append(row)
    return rows, warnings
