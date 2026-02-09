from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable

from byes.inference.backends.base import OCRResult, RiskResult

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
    payload = dict(result.payload)
    if result.text and "text" not in payload:
        payload["text"] = result.text
    if result.error and "reason" not in payload:
        payload["reason"] = result.error
    phase = "result" if str(result.status).lower() != "error" else "error"
    await _emit(
        sink,
        _base_event(
            ts_ms=ts_ms,
            frame_seq=frame_seq,
            component=component,
            category="tool",
            name="ocr.scan_text",
            phase=phase,
            status=str(result.status or "ok"),
            latency_ms=result.latency_ms,
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
) -> None:
    payload = dict(result.payload)
    hazards = list(result.hazards)
    payload["hazards"] = hazards
    if result.error and "reason" not in payload:
        payload["reason"] = result.error
    phase = "result" if str(result.status).lower() != "error" else "error"
    await _emit(
        sink,
        _base_event(
            ts_ms=ts_ms,
            frame_seq=frame_seq,
            component=component,
            category="tool",
            name="risk.hazards",
            phase=phase,
            status=str(result.status or "ok"),
            latency_ms=result.latency_ms,
            payload=payload,
            run_id=run_id,
        ),
    )
