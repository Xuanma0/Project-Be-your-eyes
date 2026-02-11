from __future__ import annotations

import itertools
from typing import Any


DEFAULT_GRID: dict[str, list[float]] = {
    "depthObsCrit": [0.45, 0.55, 0.65],
    "depthDropoffDelta": [0.6, 0.8, 1.0],
    "obsCrit": [0.20, 0.24, 0.28],
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
