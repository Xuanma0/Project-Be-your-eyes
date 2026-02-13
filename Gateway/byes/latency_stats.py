from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable


def percentile(values: list[int], p: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(0.0, min(1.0, p / 100.0))
    idx = int(math.ceil(rank * len(ordered)) - 1)
    idx = max(0, min(len(ordered) - 1, idx))
    return int(ordered[idx])


def summarize_latency(values: list[int], sample_size: int = 20) -> dict[str, Any]:
    safe_values = [int(v) for v in values if isinstance(v, (int, float)) and int(v) >= 0]
    safe_values.sort()
    size = max(0, int(sample_size))
    return {
        "count": len(safe_values),
        "p50": percentile(safe_values, 50),
        "p90": percentile(safe_values, 90),
        "p99": percentile(safe_values, 99),
        "max": max(safe_values) if safe_values else 0,
        "valuesSample": safe_values[:size] if size > 0 else [],
    }


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def extract_risk_hazard_latencies(events: Iterable[dict[str, Any]]) -> list[int]:
    latencies: list[int] = []
    for row in events:
        if not isinstance(row, dict):
            continue
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
        latency = _to_int(event.get("latencyMs"))
        if latency is not None and latency >= 0:
            latencies.append(latency)
    return latencies


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None
