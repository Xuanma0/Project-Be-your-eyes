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
    segments = list(result.segments)
    payload["segments"] = segments
    payload["segmentsCount"] = len(segments)
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
