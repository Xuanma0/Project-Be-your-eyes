from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse, urlunparse

from byes.inference.backends.base import OCRResult, RiskResult, SegResult

SCHEMA_VERSION = "byes.event.v1"

EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]


def _base_event(
    *,
    ts_ms: int | None,
    frame_seq: int | None,
    component: str,
    category: str,
    name: str,
    phase: str | None,
    status: str | None,
    latency_ms: int | None,
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "tsMs": ts_ms,
        "runId": run_id,
        "frameSeq": frame_seq,
        "component": component,
        "category": category,
        "name": name,
        "phase": phase,
        "status": status,
        "latencyMs": latency_ms,
        "payload": payload if isinstance(payload, dict) else {},
    }


async def _emit(sink: EventSink, event: dict[str, Any]) -> None:
    value = sink(event)
    if inspect.isawaitable(value):
        await asyncio.shield(value)


async def emit_ocr_events(
    result: OCRResult,
    *,
    frame_seq: int | None,
    ts_ms: int,
    sink: EventSink,
    run_id: str | None = None,
    component: str = "gateway",
    started_ts_ms: int | None = None,
    backend: str | None = None,
    model: str | None = None,
    endpoint: str | None = None,
) -> None:
    await _emit(
        sink,
        _base_event(
            ts_ms=started_ts_ms if started_ts_ms is not None else ts_ms,
            frame_seq=frame_seq,
            component=component,
            category="tool",
            name="ocr.scan_text",
            phase="start",
            status="ok",
            latency_ms=None,
            payload={},
            run_id=run_id,
        ),
    )
    payload = _sanitize_payload(result.payload)
    payload = _with_inference_metadata(payload, backend=backend, model=model, endpoint=endpoint)
    if result.text and "text" not in payload:
        payload["text"] = result.text
    if result.error and "reason" not in payload:
        payload["reason"] = result.error
    normalized_status = _normalize_status(result.status, result.error)
    phase = _phase_for_status(normalized_status)
    latency_ms = _resolve_latency_ms(result.latency_ms, started_ts_ms, ts_ms)
    await _emit(
        sink,
        _base_event(
            ts_ms=ts_ms,
            frame_seq=frame_seq,
            component=component,
            category="tool",
            name="ocr.scan_text",
            phase=phase,
            status=normalized_status,
            latency_ms=latency_ms,
            payload=payload,
            run_id=run_id,
        ),
    )


async def emit_risk_events(
    result: RiskResult,
    *,
    frame_seq: int | None,
    ts_ms: int,
    sink: EventSink,
    run_id: str | None = None,
    component: str = "gateway",
    started_ts_ms: int | None = None,
    backend: str | None = None,
    model: str | None = None,
    endpoint: str | None = None,
) -> None:
    payload = _sanitize_payload(result.payload)
    payload = _with_inference_metadata(payload, backend=backend, model=model, endpoint=endpoint)
    hazards = list(result.hazards)
    payload["hazards"] = hazards
    if result.error and "reason" not in payload:
        payload["reason"] = result.error
    normalized_status = _normalize_status(result.status, result.error)
    phase = _phase_for_status(normalized_status)
    latency_ms = _resolve_latency_ms(result.latency_ms, started_ts_ms, ts_ms)
    await _emit(
        sink,
        _base_event(
            ts_ms=ts_ms,
            frame_seq=frame_seq,
            component=component,
            category="tool",
            name="risk.hazards",
            phase=phase,
            status=normalized_status,
            latency_ms=latency_ms,
            payload=payload,
            run_id=run_id,
        ),
    )


async def emit_seg_events(
    result: SegResult,
    *,
    frame_seq: int | None,
    ts_ms: int,
    sink: EventSink,
    run_id: str | None = None,
    component: str = "gateway",
    started_ts_ms: int | None = None,
    backend: str | None = None,
    model: str | None = None,
    endpoint: str | None = None,
) -> None:
    payload = _sanitize_payload(result.payload)
    payload = _with_inference_metadata(payload, backend=backend, model=model, endpoint=endpoint)
    if "backend" not in payload:
        payload["backend"] = str(backend or "").strip().lower() or None
    if "model" not in payload:
        payload["model"] = str(model or "").strip() or None
    if "endpoint" not in payload:
        payload["endpoint"] = _sanitize_endpoint(endpoint)
    payload = _normalize_seg_payload(payload, result.segments)
    if result.error and "reason" not in payload:
        payload["reason"] = result.error
    normalized_status = _normalize_status(result.status, result.error)
    phase = _phase_for_status(normalized_status)
    latency_ms = _resolve_latency_ms(result.latency_ms, started_ts_ms, ts_ms)
    await _emit(
        sink,
        _base_event(
            ts_ms=ts_ms,
            frame_seq=frame_seq,
            component=component,
            category="tool",
            name="seg.segment",
            phase=phase,
            status=normalized_status,
            latency_ms=latency_ms,
            payload=payload,
            run_id=run_id,
        ),
    )


def _normalize_status(status: str | None, error: str | None) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"ok", "timeout", "error", "cancel"}:
        return normalized
    if "timeout" in normalized:
        return "timeout"
    if error:
        err = str(error).lower()
        if "timeout" in err:
            return "timeout"
        return "error"
    return "ok"


def _phase_for_status(status: str) -> str:
    return "error" if status in {"error", "timeout"} else "result"


def _resolve_latency_ms(latency_ms: int | None, started_ts_ms: int | None, finished_ts_ms: int | None) -> int | None:
    if isinstance(latency_ms, int):
        return max(0, int(latency_ms))
    if started_ts_ms is None or finished_ts_ms is None:
        return None
    return max(0, int(finished_ts_ms) - int(started_ts_ms))


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload) if isinstance(payload, dict) else {}
    out.pop("latencyMs", None)
    out.pop("latency_ms", None)
    out.pop("durationMs", None)
    out.pop("duration_ms", None)
    return out


def _with_inference_metadata(
    payload: dict[str, Any],
    *,
    backend: str | None,
    model: str | None,
    endpoint: str | None,
) -> dict[str, Any]:
    out = dict(payload)
    backend_val = str(backend or "").strip().lower()
    model_val = str(model or "").strip()
    endpoint_val = _sanitize_endpoint(endpoint)
    if backend_val:
        out["backend"] = backend_val
    if model_val:
        out["model"] = model_val
    if endpoint_val:
        out["endpoint"] = endpoint_val
    return out


def _sanitize_endpoint(endpoint: str | None) -> str | None:
    text = str(endpoint or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))
    return text


def _normalize_seg_payload(payload: dict[str, Any], raw_segments: Any) -> dict[str, Any]:
    out = dict(payload) if isinstance(payload, dict) else {}
    warnings_count = _to_nonnegative_int(out.get("warningsCount"))

    image_width = _to_positive_int(
        out.get("imageWidth", out.get("imageW", out.get("width"))),
    )
    image_height = _to_positive_int(
        out.get("imageHeight", out.get("imageH", out.get("height"))),
    )
    if image_width is not None:
        out["imageWidth"] = image_width
    if image_height is not None:
        out["imageHeight"] = image_height

    normalized_segments: list[dict[str, Any]] = []
    rows = raw_segments if isinstance(raw_segments, list) else []
    for row in rows:
        if not isinstance(row, dict):
            warnings_count += 1
            continue

        label = str(row.get("label", "")).strip()
        if not label:
            label = "unknown"
            warnings_count += 1

        score = _to_float(row.get("score"))
        if score is None:
            score = 0.0
            warnings_count += 1
        score_clamped = _clamp_float(score, 0.0, 1.0)
        if score_clamped != score:
            warnings_count += 1
        score = score_clamped

        bbox_raw = row.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            warnings_count += 1
            continue
        coords: list[float] = []
        parse_failed = False
        for value in bbox_raw:
            parsed = _to_float(value)
            if parsed is None:
                parse_failed = True
                break
            coords.append(parsed)
        if parse_failed:
            warnings_count += 1
            continue

        x0, y0, x1, y1 = coords
        if x0 > x1:
            x0, x1 = x1, x0
            warnings_count += 1
        if y0 > y1:
            y0, y1 = y1, y0
            warnings_count += 1

        if image_width is not None:
            orig_x0, orig_x1 = x0, x1
            x0 = _clamp_float(x0, 0.0, float(image_width))
            x1 = _clamp_float(x1, 0.0, float(image_width))
            if x0 != orig_x0 or x1 != orig_x1:
                warnings_count += 1
        if image_height is not None:
            orig_y0, orig_y1 = y0, y1
            y0 = _clamp_float(y0, 0.0, float(image_height))
            y1 = _clamp_float(y1, 0.0, float(image_height))
            if y0 != orig_y0 or y1 != orig_y1:
                warnings_count += 1

        if x1 <= x0:
            x1 = min(float(image_width), x0 + 1.0) if image_width is not None else x0 + 1.0
            warnings_count += 1
        if y1 <= y0:
            y1 = min(float(image_height), y0 + 1.0) if image_height is not None else y0 + 1.0
            warnings_count += 1

        normalized_segments.append(
            {
                "label": label,
                "score": score,
                "bbox": [x0, y0, x1, y1],
            }
        )

    out["segments"] = normalized_segments
    out["segmentsCount"] = len(normalized_segments)
    if warnings_count > 0:
        out["warningsCount"] = int(warnings_count)
    elif "warningsCount" in out:
        out.pop("warningsCount", None)
    return out


def _to_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _to_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    if parsed <= 0:
        return None
    return parsed


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _clamp_float(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, float(value)))
