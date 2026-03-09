from __future__ import annotations

import asyncio
import inspect
import math
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse, urlunparse

from byes.inference.backends.base import OCRResult, RiskResult, SegResult, DetResult, DepthResult, SlamResult

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
            name="ocr.read",
            phase="start",
            status="ok",
            latency_ms=None,
            payload={},
            run_id=run_id,
        ),
    )
    payload = _sanitize_payload(result.payload)
    payload = _with_inference_metadata(payload, backend=backend, model=model, endpoint=endpoint)
    payload = _normalize_ocr_payload(payload, raw_lines=result.lines, text_hint=result.text, frame_seq=frame_seq, run_id=run_id)
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
            name="ocr.read",
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


async def emit_det_events(
    result: DetResult,
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
    objects = [dict(item) for item in result.objects if isinstance(item, dict)]
    payload["objects"] = objects
    payload["objectsCount"] = int(payload.get("objectsCount", len(objects)) or len(objects))
    payload.setdefault("schemaVersion", "byes.det.v1")
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
            name="det.objects",
            phase=phase,
            status=normalized_status,
            latency_ms=latency_ms,
            payload=payload,
            run_id=run_id,
        ),
    )


async def emit_depth_events(
    result: DepthResult,
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
    payload = _normalize_depth_payload(payload, result.grid)
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
            name="depth.estimate",
            phase=phase,
            status=normalized_status,
            latency_ms=latency_ms,
            payload=payload,
            run_id=run_id,
        ),
    )


async def emit_slam_pose_events(
    result: SlamResult,
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
    payload = _normalize_slam_payload(payload, tracking_state=result.tracking_state, pose=result.pose)
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
            name="slam.pose",
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

        normalized_row: dict[str, Any] = {
            "label": label,
            "score": score,
            "bbox": [x0, y0, x1, y1],
        }
        track_id_raw = row.get("trackId")
        if track_id_raw is not None:
            if isinstance(track_id_raw, str):
                track_id = track_id_raw.strip()
                if track_id:
                    normalized_row["trackId"] = track_id
                else:
                    warnings_count += 1
            else:
                warnings_count += 1

        track_state_raw = row.get("trackState")
        if track_state_raw is not None:
            if isinstance(track_state_raw, str):
                track_state = track_state_raw.strip().lower()
                if track_state in {"init", "track", "lost"}:
                    normalized_row["trackState"] = track_state
                else:
                    warnings_count += 1
            else:
                warnings_count += 1
        normalized_mask, mask_warnings = _normalize_seg_mask(row.get("mask"))
        warnings_count += int(mask_warnings)
        if isinstance(normalized_mask, dict):
            normalized_row["mask"] = normalized_mask

        normalized_segments.append(normalized_row)

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


def _normalize_seg_mask(mask_raw: Any) -> tuple[dict[str, Any] | None, int]:
    if mask_raw is None:
        return None, 0
    if not isinstance(mask_raw, dict):
        return None, 1

    fmt = str(mask_raw.get("format", "")).strip()
    if fmt != "rle_v1":
        return None, 1

    size = mask_raw.get("size")
    if not isinstance(size, list) or len(size) != 2:
        return None, 1
    try:
        h = int(size[0])
        w = int(size[1])
    except Exception:
        return None, 1
    if h <= 0 or w <= 0:
        return None, 1

    counts_raw = mask_raw.get("counts")
    if not isinstance(counts_raw, list):
        return None, 1
    counts: list[int] = []
    total = 0
    for value in counts_raw:
        try:
            parsed = int(value)
        except Exception:
            return None, 1
        if parsed < 0:
            return None, 1
        counts.append(parsed)
        total += parsed

    if total != h * w:
        return None, 1

    return {"format": "rle_v1", "size": [h, w], "counts": counts}, 0


def _normalize_depth_payload(payload: dict[str, Any], raw_grid: Any) -> dict[str, Any]:
    out = dict(payload) if isinstance(payload, dict) else {}
    warnings_count = _to_nonnegative_int(out.get("warningsCount"))

    image_width = _to_positive_int(out.get("imageWidth"))
    image_height = _to_positive_int(out.get("imageHeight"))
    if image_width is not None:
        out["imageWidth"] = image_width
    if image_height is not None:
        out["imageHeight"] = image_height

    grid_raw = raw_grid if isinstance(raw_grid, dict) else out.get("grid")
    grid, grid_warnings = _normalize_depth_grid(grid_raw)
    warnings_count += grid_warnings
    if isinstance(grid, dict):
        out["grid"] = grid
        values = grid.get("values")
        values_count = len(values) if isinstance(values, list) else 0
        out["valuesCount"] = values_count
        out["gridCount"] = 1
    else:
        out.pop("grid", None)
        out["valuesCount"] = 0
        out["gridCount"] = 0

    meta_raw = out.get("meta")
    meta_obj, meta_warnings = _normalize_depth_meta(meta_raw)
    warnings_count += int(meta_warnings)
    if isinstance(meta_obj, dict):
        out["meta"] = meta_obj
    elif "meta" in out:
        out.pop("meta", None)

    if warnings_count > 0:
        out["warningsCount"] = int(warnings_count)
    elif "warningsCount" in out:
        out.pop("warningsCount", None)
    return out


def _normalize_depth_meta(raw: Any) -> tuple[dict[str, Any] | None, int]:
    if raw is None:
        return None, 0
    if not isinstance(raw, dict):
        return None, 1
    warnings = 0
    out: dict[str, Any] = {}
    provider_raw = raw.get("provider")
    if provider_raw is not None:
        provider_text = str(provider_raw).strip()
        if provider_text:
            out["provider"] = provider_text
        else:
            warnings += 1
    ref_view_raw = raw.get("refViewStrategy")
    if ref_view_raw is not None:
        ref_view_text = str(ref_view_raw).strip()
        if ref_view_text:
            out["refViewStrategy"] = ref_view_text
        else:
            out["refViewStrategy"] = None
    pose_used_raw = raw.get("poseUsed")
    if pose_used_raw is not None:
        if isinstance(pose_used_raw, bool):
            out["poseUsed"] = pose_used_raw
        else:
            warnings += 1
    meta_warnings_raw = raw.get("warningsCount")
    if meta_warnings_raw is not None:
        try:
            parsed = int(meta_warnings_raw)
        except Exception:
            warnings += 1
        else:
            if parsed < 0:
                warnings += 1
            else:
                out["warningsCount"] = parsed
    if not out:
        return None, warnings
    return out, warnings


def _normalize_slam_payload(payload: dict[str, Any], *, tracking_state: str | None, pose: Any) -> dict[str, Any]:
    out = dict(payload) if isinstance(payload, dict) else {}
    warnings_count = _to_nonnegative_int(out.get("warningsCount"))
    out["schemaVersion"] = "byes.slam_pose.v1"

    state = str(out.get("trackingState", tracking_state or "")).strip().lower()
    if state not in {"tracking", "lost", "relocalized", "initializing"}:
        if state:
            warnings_count += 1
        state = "unknown"
    out["trackingState"] = state

    pose_raw = pose if isinstance(pose, dict) else out.get("pose")
    pose_obj = pose_raw if isinstance(pose_raw, dict) else {}
    t_raw = pose_obj.get("t")
    q_raw = pose_obj.get("q")
    t: list[float] = [0.0, 0.0, 0.0]
    q: list[float] = [0.0, 0.0, 0.0, 1.0]
    if isinstance(t_raw, list) and len(t_raw) == 3:
        parsed_t: list[float] = []
        for value in t_raw:
            parsed = _to_float(value)
            if parsed is None:
                parsed_t = []
                break
            parsed_t.append(parsed)
        if len(parsed_t) == 3:
            t = parsed_t
        else:
            warnings_count += 1
    else:
        warnings_count += 1

    if isinstance(q_raw, list) and len(q_raw) == 4:
        parsed_q: list[float] = []
        for value in q_raw:
            parsed = _to_float(value)
            if parsed is None:
                parsed_q = []
                break
            parsed_q.append(parsed)
        if len(parsed_q) == 4:
            norm = math.sqrt(sum((item * item) for item in parsed_q))
            if norm > 1e-9:
                q = [item / norm for item in parsed_q]
                if abs(norm - 1.0) > 1e-3:
                    warnings_count += 1
            else:
                warnings_count += 1
        else:
            warnings_count += 1
    else:
        warnings_count += 1

    pose_out: dict[str, Any] = {"t": t, "q": q}
    frame = str(pose_obj.get("frame", "")).strip().lower()
    if frame in {"world_to_cam", "cam_to_world"}:
        pose_out["frame"] = frame
    map_id = pose_obj.get("mapId")
    map_id_text = str(map_id).strip() if map_id is not None else ""
    if map_id_text:
        pose_out["mapId"] = map_id_text
    cov = pose_obj.get("cov")
    if isinstance(cov, dict):
        pose_out["cov"] = cov
    out["pose"] = pose_out

    if warnings_count > 0:
        out["warningsCount"] = int(warnings_count)
    elif "warningsCount" in out:
        out.pop("warningsCount", None)
    return out


def _normalize_ocr_payload(
    payload: dict[str, Any],
    *,
    raw_lines: Any,
    text_hint: str | None,
    frame_seq: int | None,
    run_id: str | None,
) -> dict[str, Any]:
    out = dict(payload) if isinstance(payload, dict) else {}
    warnings_count = _to_nonnegative_int(out.get("warningsCount"))

    image_width = _to_positive_int(out.get("imageWidth"))
    image_height = _to_positive_int(out.get("imageHeight"))
    if image_width is not None:
        out["imageWidth"] = image_width
    if image_height is not None:
        out["imageHeight"] = image_height

    normalized_lines: list[dict[str, Any]] = []
    rows = raw_lines if isinstance(raw_lines, list) else out.get("lines")
    rows = rows if isinstance(rows, list) else []
    for row in rows:
        if isinstance(row, str):
            text = str(row).strip()
            if not text:
                warnings_count += 1
                continue
            normalized_lines.append({"text": text})
            continue
        if not isinstance(row, dict):
            warnings_count += 1
            continue
        text = str(row.get("text", "")).strip()
        if not text:
            warnings_count += 1
            continue
        normalized_row: dict[str, Any] = {"text": text}
        score = _to_float(row.get("score"))
        if score is not None:
            score_clamped = _clamp_float(score, 0.0, 1.0)
            if score_clamped != score:
                warnings_count += 1
            normalized_row["score"] = score_clamped
        bbox_raw = row.get("bbox")
        if isinstance(bbox_raw, list) and len(bbox_raw) == 4:
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
            else:
                x0, y0, x1, y1 = coords
                if x0 > x1:
                    x0, x1 = x1, x0
                    warnings_count += 1
                if y0 > y1:
                    y0, y1 = y1, y0
                    warnings_count += 1
                if image_width is not None:
                    old = (x0, x1)
                    x0 = _clamp_float(x0, 0.0, float(image_width))
                    x1 = _clamp_float(x1, 0.0, float(image_width))
                    if old != (x0, x1):
                        warnings_count += 1
                if image_height is not None:
                    old = (y0, y1)
                    y0 = _clamp_float(y0, 0.0, float(image_height))
                    y1 = _clamp_float(y1, 0.0, float(image_height))
                    if old != (y0, y1):
                        warnings_count += 1
                if x1 <= x0:
                    x1 = x0 + 1.0
                    warnings_count += 1
                if y1 <= y0:
                    y1 = y0 + 1.0
                    warnings_count += 1
                normalized_row["bbox"] = [x0, y0, x1, y1]
        normalized_lines.append(normalized_row)

    if not normalized_lines:
        fallback_text = str(out.get("text", "")).strip() or str(text_hint or "").strip()
        if fallback_text:
            normalized_lines.append({"text": fallback_text})
        elif "reason" not in out:
            warnings_count += 1

    merged_text = " ".join(
        str(item.get("text", "")).strip() for item in normalized_lines if isinstance(item, dict) and str(item.get("text", "")).strip()
    ).strip()
    out["schemaVersion"] = "byes.ocr.v1"
    out["runId"] = run_id
    out["frameSeq"] = frame_seq
    out["lines"] = normalized_lines
    out["linesCount"] = len(normalized_lines)
    if merged_text:
        out["text"] = merged_text
    if warnings_count > 0:
        out["warningsCount"] = int(warnings_count)
    elif "warningsCount" in out:
        out.pop("warningsCount", None)
    return out


def _normalize_depth_grid(raw: Any) -> tuple[dict[str, Any] | None, int]:
    if not isinstance(raw, dict):
        return None, 0

    warnings = 0
    fmt = str(raw.get("format", "")).strip()
    if fmt != "grid_u16_mm_v1":
        return None, 1
    unit = str(raw.get("unit", "")).strip().lower()
    if unit != "mm":
        return None, 1

    size_raw = raw.get("size")
    if not isinstance(size_raw, list) or len(size_raw) != 2:
        return None, 1
    try:
        gw = int(size_raw[0])
        gh = int(size_raw[1])
    except Exception:
        return None, 1
    if gw <= 0 or gh <= 0:
        return None, 1

    values_raw = raw.get("values")
    if not isinstance(values_raw, list):
        return None, 1
    values: list[int] = []
    for value in values_raw:
        try:
            parsed = int(value)
        except Exception:
            return None, 1
        clamped = max(0, min(65535, parsed))
        if clamped != parsed:
            warnings += 1
        values.append(clamped)
    if len(values) != gw * gh:
        return None, warnings + 1
    return {"format": "grid_u16_mm_v1", "size": [gw, gh], "unit": "mm", "values": values}, warnings
