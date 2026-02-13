from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

from byes.latency_stats import summarize_latency


DEFAULT_GRID: dict[str, list[float]] = {
    "depthObsCrit": [0.35, 0.45, 0.55, 0.65],
    "depthDropoffDelta": [0.4, 0.6, 0.8, 1.0],
    "obsCrit": [0.16, 0.20, 0.24, 0.28],
}


def expand_grid(grid: dict[str, list[float]]) -> list[dict[str, float]]:
    keys: list[str] = []
    values: list[list[float]] = []
    for key, raw_values in grid.items():
        if not isinstance(raw_values, list) or not raw_values:
            continue
        parsed: list[float] = []
        for item in raw_values:
            try:
                parsed.append(float(item))
            except Exception:  # noqa: BLE001
                continue
        if not parsed:
            continue
        keys.append(str(key))
        values.append(parsed)
    if not keys:
        return [{}]
    rows: list[dict[str, float]] = []
    for combo in itertools.product(*values):
        row = {key: float(value) for key, value in zip(keys, combo)}
        rows.append(row)
    return rows


def select_best_candidates(
    results: list[dict[str, Any]],
    *,
    must_zero_critical_fn: bool = True,
    top_k: int = 5,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    ranked = [row for row in results if isinstance(row, dict)]
    if must_zero_critical_fn:
        ranked = [row for row in ranked if _as_int(row.get("critical_fn")) == 0]
    if not ranked:
        return None, []
    ranked.sort(key=_calibration_sort_key)
    safe_top_k = max(1, int(top_k))
    return ranked[0], ranked[:safe_top_k]


def _calibration_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    fp_total = _as_int(row.get("fp_total"), fallback=10**9)
    quality = _as_float(row.get("qualityScore"), fallback=-10**9)
    latency_p90 = _as_int(row.get("riskLatencyP90"), fallback=10**9)
    size = _as_int(row.get("size"), fallback=10**9)
    params = row.get("params")
    params_key = repr(params) if isinstance(params, dict) else ""
    return (
        fp_total,
        -quality,
        latency_p90,
        size,
        params_key,
    )


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        if value is None:
            return int(fallback)
        return int(float(value))
    except Exception:  # noqa: BLE001
        return int(fallback)


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None:
            return float(fallback)
        return float(value)
    except Exception:  # noqa: BLE001
        return float(fallback)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def collect_risk_hazard_result_latencies(events: list[dict[str, Any]]) -> list[int]:
    latencies: list[int] = []
    for row in events:
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("category", "")).strip().lower() != "tool":
            continue
        if str(event.get("name", "")).strip().lower() != "risk.hazards":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        value = _as_int_or_none(event.get("latencyMs"))
        if value is None:
            continue
        latencies.append(value)
    return latencies


def validate_risk_latency_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = collect_risk_hazard_result_latencies(events)
    positive = [value for value in latencies if int(value) > 0]
    all_stats = summarize_latency(latencies)
    positive_stats = summarize_latency(positive)
    valid = bool(positive)
    return {
        "valid": valid,
        "totalCount": int(all_stats.get("count", 0) or 0),
        "positiveCount": int(positive_stats.get("count", 0) or 0),
        "p50": int(positive_stats.get("p50", 0) or 0) if valid else None,
        "p90": int(positive_stats.get("p90", 0) or 0) if valid else None,
        "p99": int(positive_stats.get("p99", 0) or 0) if valid else None,
        "max": int(positive_stats.get("max", 0) or 0) if valid else None,
        "valuesSample": positive_stats.get("valuesSample", []) if valid else [],
        "allValuesSample": all_stats.get("valuesSample", []),
    }


def build_calibration_latency_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    info = validate_risk_latency_from_events(events)
    notes: list[str] = []
    p90: int | None = info.get("p90") if isinstance(info, dict) else None
    if not bool(info.get("valid", False)):
        p90 = None
        notes.append("latency_invalid")
    return {
        "riskLatencyP90": p90,
        "riskLatency": info,
        "riskLatencyRawCount": len(collect_risk_hazard_result_latencies(events)),
        "notes": notes,
    }


def _as_int_or_none(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(float(value))
    except Exception:  # noqa: BLE001
        return None
