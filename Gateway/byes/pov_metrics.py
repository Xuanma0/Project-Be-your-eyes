from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def load_pov_ir_from_run_package(run_package_dir: Path | str) -> dict[str, Any] | None:
    root = Path(run_package_dir)
    if not root.exists() or not root.is_dir():
        return None

    manifest: dict[str, Any] | None = None
    for name in ("manifest.json", "run_manifest.json"):
        path = root / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if isinstance(payload, dict):
            manifest = payload
            break
    if not isinstance(manifest, dict):
        return None

    rel = str(manifest.get("povIrJson", "")).strip()
    if not rel:
        return None
    pov_path = root / rel
    if not pov_path.exists() or not pov_path.is_file():
        return None
    try:
        payload = json.loads(pov_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def compute_pov_metrics(pov_ir: dict[str, Any] | None, events_v1: list[dict[str, Any]] | None) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "present": False,
        "schemaVersion": None,
        "source": None,
        "counts": {
            "decisions": 0,
            "events": 0,
            "highlights": 0,
            "tokens": 0,
        },
        "time": {
            "t0Ms": None,
            "t1Ms": None,
            "durationMs": None,
            "decisionPerMin": None,
        },
        "budget": {
            "tokenCharsTotal": 0,
            "tokenApprox": 0,
            "highlightsCharsTotal": 0,
        },
    }

    if isinstance(pov_ir, dict):
        metrics["present"] = True
        metrics["source"] = "povIrJson"
        metrics["schemaVersion"] = str(pov_ir.get("schemaVersion", "")).strip() or None
        _fill_from_pov_ir(metrics, pov_ir)
        _finalize_time_and_budget(metrics)
        return metrics

    rows = [row for row in (events_v1 or []) if isinstance(row, dict)]
    pov_rows = _collect_pov_event_rows(rows)
    if pov_rows:
        metrics["present"] = True
        metrics["source"] = "eventsV1Derived"
        _fill_from_pov_events(metrics, pov_rows)
        _finalize_time_and_budget(metrics)
    return metrics


def _fill_from_pov_ir(metrics: dict[str, Any], pov_ir: dict[str, Any]) -> None:
    decisions = _as_dict_list(pov_ir.get("decisionPoints"))
    events = _as_dict_list(pov_ir.get("events"))
    highlights = _as_dict_list(pov_ir.get("highlights"))
    tokens = _as_dict_list(pov_ir.get("tokens"))

    counts = metrics["counts"]
    counts["decisions"] = len(decisions)
    counts["events"] = len(events)
    counts["highlights"] = len(highlights)
    counts["tokens"] = len(tokens)

    t0_candidates: list[int] = []
    t1_candidates: list[int] = []

    for row in decisions:
        t0 = _as_non_negative_int(row.get("t0Ms"))
        t1 = _as_non_negative_int(row.get("t1Ms"))
        if t0 is not None:
            t0_candidates.append(t0)
            t1_candidates.append(t0)
        if t1 is not None:
            t1_candidates.append(t1)

    for row in events + highlights + tokens:
        t_val = _as_non_negative_int(row.get("tMs"))
        if t_val is None:
            t_val = _as_non_negative_int(row.get("tsMs"))
        if t_val is None:
            t_val = _as_non_negative_int(row.get("t0Ms"))
        if t_val is not None:
            t0_candidates.append(t_val)
            t1_candidates.append(t_val)

    if t0_candidates:
        metrics["time"]["t0Ms"] = min(t0_candidates)
    if t1_candidates:
        metrics["time"]["t1Ms"] = max(t1_candidates)

    token_chars = 0
    for row in tokens:
        token_chars += len(_read_primary_text(row))
    metrics["budget"]["tokenCharsTotal"] = token_chars

    highlight_chars = 0
    for row in highlights:
        highlight_chars += len(_read_primary_text(row))
    metrics["budget"]["highlightsCharsTotal"] = highlight_chars


def _collect_pov_event_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip().lower()
        if not name.startswith("pov."):
            continue
        out.append(row)
    return out


def _fill_from_pov_events(metrics: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    counts = metrics["counts"]
    t0_candidates: list[int] = []
    t1_candidates: list[int] = []
    token_chars = 0
    highlight_chars = 0

    for row in rows:
        name = str(row.get("name", "")).strip().lower()
        if name == "pov.decision":
            counts["decisions"] += 1
        elif name == "pov.event":
            counts["events"] += 1
        elif name == "pov.highlight":
            counts["highlights"] += 1
        elif name == "pov.token":
            counts["tokens"] += 1

        ts_ms = _as_non_negative_int(row.get("tsMs"))
        if ts_ms is not None:
            t0_candidates.append(ts_ms)
            t1_candidates.append(ts_ms)

        payload = row.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}
        if name == "pov.token":
            token_chars += len(_read_primary_text(payload_dict))
        if name == "pov.highlight":
            highlight_chars += len(_read_primary_text(payload_dict))

    metrics["budget"]["tokenCharsTotal"] = token_chars
    metrics["budget"]["highlightsCharsTotal"] = highlight_chars

    if t0_candidates:
        metrics["time"]["t0Ms"] = min(t0_candidates)
    if t1_candidates:
        metrics["time"]["t1Ms"] = max(t1_candidates)


def _finalize_time_and_budget(metrics: dict[str, Any]) -> None:
    t0_ms = _as_non_negative_int(metrics.get("time", {}).get("t0Ms"))
    t1_ms = _as_non_negative_int(metrics.get("time", {}).get("t1Ms"))
    duration_ms: int | None = None
    if t0_ms is not None and t1_ms is not None and t1_ms >= t0_ms:
        duration_ms = t1_ms - t0_ms
    metrics["time"]["durationMs"] = duration_ms

    decisions = int(metrics.get("counts", {}).get("decisions", 0) or 0)
    decision_per_min: float | None = None
    if duration_ms is not None and duration_ms > 0:
        decision_per_min = round((decisions * 60000.0) / float(duration_ms), 3)
    metrics["time"]["decisionPerMin"] = decision_per_min

    token_chars = int(metrics.get("budget", {}).get("tokenCharsTotal", 0) or 0)
    metrics["budget"]["tokenApprox"] = int(math.ceil(token_chars / 4.0)) if token_chars > 0 else 0


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _as_non_negative_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = int(float(value))
        return out if out >= 0 else None
    except Exception:
        return None


def _read_primary_text(payload: dict[str, Any]) -> str:
    for key in ("text", "summary", "content"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""
