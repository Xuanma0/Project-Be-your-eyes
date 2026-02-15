from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from byes.event_normalizer import collect_normalized_ws_events
from byes.hazards.taxonomy_v1 import normalize_hazard_kind, normalize_hazards
from byes.latency_stats import summarize_latency

_FRAME_RE = re.compile(r"(?:frame[_-]?|seq[_-]?)(\d+)", re.IGNORECASE)


def load_gt_ocr_jsonl(path: Path) -> dict[int, str]:
    rows: dict[int, str] = {}
    for item in _iter_jsonl(path):
        if not isinstance(item, dict):
            continue
        seq = _extract_frame_seq(item)
        if seq is None:
            continue
        text = _read_text(item)
        rows[seq] = text
    return rows


def load_gt_risk_jsonl(
    path: Path,
    *,
    return_meta: bool = False,
) -> dict[int, list[dict[str, Any]]] | tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    rows: dict[int, list[dict[str, Any]]] = {}
    meta = _new_hazard_norm_meta()
    for item in _iter_jsonl(path):
        if not isinstance(item, dict):
            continue
        seq = _extract_frame_seq(item)
        if seq is None:
            continue
        hazards = _extract_hazards(item, norm_meta=meta)
        rows[seq] = hazards
    finalized = _finalize_hazard_norm_meta(meta)
    if return_meta:
        return rows, finalized
    return rows


def load_gt_seg_v1(path: Path) -> dict[int, list[dict[str, Any]]]:
    records: dict[int, list[dict[str, Any]]] = {}
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        for item in _iter_jsonl(path):
            if not isinstance(item, dict):
                continue
            seq = _extract_frame_seq(item)
            if seq is None:
                continue
            objects = item.get("objects")
            if not isinstance(objects, list):
                continue
            normalized = [_normalize_seg_object(obj) for obj in objects]
            records[seq] = [obj for obj in normalized if isinstance(obj, dict)]
        return records

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return records

    frames: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        rows = payload.get("frames")
        if isinstance(rows, list):
            frames = [row for row in rows if isinstance(row, dict)]
    elif isinstance(payload, list):
        frames = [row for row in payload if isinstance(row, dict)]

    for row in frames:
        seq = _extract_frame_seq(row)
        if seq is None:
            continue
        objects = row.get("objects")
        if not isinstance(objects, list):
            continue
        normalized = [_normalize_seg_object(obj) for obj in objects]
        records[seq] = [obj for obj in normalized if isinstance(obj, dict)]
    return records


def load_gt_depth_v1(path: Path) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return records

    frames: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        rows = payload.get("frames")
        if isinstance(rows, list):
            frames = [row for row in rows if isinstance(row, dict)]
    elif isinstance(payload, list):
        frames = [row for row in payload if isinstance(row, dict)]

    for row in frames:
        seq = _extract_frame_seq(row)
        if seq is None:
            continue
        grid = _normalize_depth_grid_object(row.get("grid"))
        if not isinstance(grid, dict):
            continue
        record: dict[str, Any] = {"grid": grid}
        width = _parse_int(row.get("imageWidth"))
        height = _parse_int(row.get("imageHeight"))
        if width is not None and width > 0:
            record["imageWidth"] = width
        if height is not None and height > 0:
            record["imageHeight"] = height
        records[seq] = record
    return records


def extract_pred_seg_from_ws_events(
    ws_events_jsonl_path: Path,
) -> tuple[dict[int, list[dict[str, Any]]], set[int], list[int]]:
    pred_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    pred_event_frames: set[int] = set()
    latencies: list[int] = []

    normalized_summary = collect_normalized_ws_events(ws_events_jsonl_path)
    normalized_events = normalized_summary.get("events", [])
    for event in normalized_events:
        if not isinstance(event, dict):
            continue
        if str(event.get("name", "")).strip().lower() != "seg.segment":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        seq = _parse_int(event.get("frameSeq"))
        if seq is None:
            continue
        pred_event_frames.add(seq)
        latency = _parse_int(event.get("latencyMs"))
        if latency is not None and latency >= 0:
            latencies.append(latency)
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        segments = payload.get("segments")
        if not isinstance(segments, list):
            continue
        for raw in segments:
            item = _normalize_seg_object(raw)
            if item is not None:
                pred_map[seq].append(item)

    if normalized_events:
        compact = {seq: rows for seq, rows in pred_map.items()}
        return compact, pred_event_frames, latencies

    for row in _iter_jsonl(ws_events_jsonl_path):
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        name = str(event.get("name", "")).strip().lower()
        phase = str(event.get("phase", "")).strip().lower()
        status = str(event.get("status", "")).strip().lower()
        if name != "seg.segment" or (phase and phase != "result") or (status and status != "ok"):
            continue
        seq = _extract_frame_seq(event)
        if seq is None:
            continue
        pred_event_frames.add(seq)
        latency = _extract_latency_ms(event)
        if latency is not None and latency >= 0:
            latencies.append(latency)
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        segments = payload.get("segments")
        if not isinstance(segments, list):
            continue
        for raw in segments:
            item = _normalize_seg_object(raw)
            if item is not None:
                pred_map[seq].append(item)

    compact = {seq: rows for seq, rows in pred_map.items()}
    return compact, pred_event_frames, latencies


def extract_pred_depth_from_ws_events(
    ws_events_jsonl_path: Path,
) -> tuple[dict[int, dict[str, Any]], set[int], list[int]]:
    pred_map: dict[int, dict[str, Any]] = {}
    pred_event_frames: set[int] = set()
    latencies: list[int] = []

    normalized_summary = collect_normalized_ws_events(ws_events_jsonl_path)
    normalized_events = normalized_summary.get("events", [])
    for event in normalized_events:
        if not isinstance(event, dict):
            continue
        if str(event.get("name", "")).strip().lower() != "depth.estimate":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        seq = _parse_int(event.get("frameSeq"))
        if seq is None:
            continue
        pred_event_frames.add(seq)
        latency = _parse_int(event.get("latencyMs"))
        if latency is not None and latency >= 0:
            latencies.append(latency)
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        grid = _normalize_depth_grid_object(payload.get("grid"))
        if not isinstance(grid, dict):
            continue
        row: dict[str, Any] = {"grid": grid}
        width = _parse_int(payload.get("imageWidth"))
        height = _parse_int(payload.get("imageHeight"))
        if width is not None and width > 0:
            row["imageWidth"] = width
        if height is not None and height > 0:
            row["imageHeight"] = height
        pred_map[seq] = row

    if normalized_events:
        return pred_map, pred_event_frames, latencies

    for row in _iter_jsonl(ws_events_jsonl_path):
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("name", "")).strip().lower() != "depth.estimate":
            continue
        if str(event.get("phase", "")).strip().lower() not in {"", "result"}:
            continue
        if str(event.get("status", "")).strip().lower() not in {"", "ok"}:
            continue
        seq = _extract_frame_seq(event)
        if seq is None:
            continue
        pred_event_frames.add(seq)
        latency = _extract_latency_ms(event)
        if latency is not None and latency >= 0:
            latencies.append(latency)
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        grid = _normalize_depth_grid_object(payload.get("grid"))
        if not isinstance(grid, dict):
            continue
        out: dict[str, Any] = {"grid": grid}
        width = _parse_int(payload.get("imageWidth"))
        height = _parse_int(payload.get("imageHeight"))
        if width is not None and width > 0:
            out["imageWidth"] = width
        if height is not None and height > 0:
            out["imageHeight"] = height
        pred_map[seq] = out

    return pred_map, pred_event_frames, latencies


def extract_pred_ocr_from_ws_events(ws_events_jsonl_path: Path) -> dict[int, dict[str, Any]]:
    normalized_summary = collect_normalized_ws_events(ws_events_jsonl_path)
    normalized_events = normalized_summary.get("events", [])
    preds: dict[int, dict[str, Any]] = {}
    for event in normalized_events:
        name = str(event.get("name", "")).strip().lower()
        phase = str(event.get("phase", "")).strip().lower()
        if name != "ocr.scan_text":
            continue
        if phase and phase not in {"result", "info"}:
            continue
        seq = _parse_int(event.get("frameSeq"))
        if seq is None:
            continue
        payload = event.get("payload")
        text = ""
        if isinstance(payload, dict):
            text = str(payload.get("text", "")).strip()
            if not text:
                text = str(payload.get("summary", "")).strip()
        if not text:
            text = str(event.get("name", "")).strip() if False else ""
        if not text:
            continue
        latency_ms = _parse_int(event.get("latencyMs"))
        existing = preds.get(seq)
        if existing is None or len(text) > len(str(existing.get("text", ""))):
            preds[seq] = {"text": text, "latencyMs": latency_ms}

    if preds:
        return preds

    for row in _iter_jsonl(ws_events_jsonl_path):
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            if isinstance(row, dict):
                event = row
            else:
                continue

        seq = _extract_frame_seq(event)
        if seq is None:
            continue
        if not _looks_like_ocr_event(event):
            continue

        text = _extract_ocr_text(event)
        if not text:
            continue

        latency_ms = _extract_latency_ms(event)
        existing = preds.get(seq)
        if existing is None or len(text) > len(str(existing.get("text", ""))):
            preds[seq] = {"text": text, "latencyMs": latency_ms}
    return preds


def extract_pred_hazards_from_ws_events(
    ws_events_jsonl_path: Path,
    *,
    return_meta: bool = False,
) -> dict[int, list[dict[str, Any]]] | tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    normalized_summary = collect_normalized_ws_events(ws_events_jsonl_path)
    normalized_events = normalized_summary.get("events", [])
    meta = _new_hazard_norm_meta()
    normalized_preds: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in normalized_events:
        name = str(event.get("name", "")).strip().lower()
        if name not in {"risk.hazards", "risk.depth"}:
            continue
        seq = _parse_int(event.get("frameSeq"))
        if seq is None:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        hazards = payload.get("hazards")
        if not isinstance(hazards, list):
            continue
        normalized_hazards, warnings = normalize_hazards([item for item in hazards if isinstance(item, dict)])
        _ingest_hazard_warnings(meta, warnings)
        for row in normalized_hazards:
            normalized_preds[seq].append(dict(row))

    if normalized_preds:
        compact: dict[int, list[dict[str, Any]]] = {}
        for seq, hazards in normalized_preds.items():
            seen: set[str] = set()
            uniq: list[dict[str, Any]] = []
            for hazard in hazards:
                kind = str(hazard.get("hazardKind", "")).strip().lower()
                if not kind or kind in seen:
                    continue
                seen.add(kind)
                row = {"hazardKind": kind}
                severity = str(hazard.get("severity", "warning")).strip().lower()
                if severity in {"critical", "warning", "info"}:
                    row["severity"] = severity
                uniq.append(row)
            compact[seq] = uniq
        finalized = _finalize_hazard_norm_meta(meta)
        if return_meta:
            return compact, finalized
        return compact

    preds: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in _iter_jsonl(ws_events_jsonl_path):
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            if isinstance(row, dict):
                event = row
            else:
                continue

        seq = _extract_frame_seq(event)
        if seq is None:
            continue
        hazards = _extract_hazards(event, norm_meta=meta)
        if not hazards:
            continue
        preds[seq].extend(hazards)

    compact: dict[int, list[dict[str, Any]]] = {}
    for seq, hazards in preds.items():
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for hazard in hazards:
            kind = str(hazard.get("hazardKind", "")).strip().lower()
            if not kind:
                continue
            if kind in seen:
                continue
            seen.add(kind)
            row = {"hazardKind": kind}
            severity = str(hazard.get("severity", "warning")).strip().lower()
            if severity in {"critical", "warning", "info"}:
                row["severity"] = severity
            uniq.append(row)
        compact[seq] = uniq
    finalized = _finalize_hazard_norm_meta(meta)
    if return_meta:
        return compact, finalized
    return compact


def extract_ocr_intent_frames_from_ws_events(ws_events_jsonl_path: Path) -> set[int]:
    normalized_summary = collect_normalized_ws_events(ws_events_jsonl_path)
    normalized_events = normalized_summary.get("events", [])
    intent_frames: set[int] = set()
    for event in normalized_events:
        name = str(event.get("name", "")).strip().lower()
        phase = str(event.get("phase", "")).strip().lower()
        if name == "ocr.scan_text" and phase == "start":
            seq = _parse_int(event.get("frameSeq"))
            if seq is not None:
                intent_frames.add(seq)
    if intent_frames:
        return intent_frames

    intent_frames: set[int] = set()
    for row in _iter_jsonl(ws_events_jsonl_path):
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            if isinstance(row, dict):
                event = row
            else:
                continue
        seq = _extract_frame_seq(event)
        if seq is None:
            continue
        if _looks_like_ocr_intent_event(event):
            intent_frames.add(seq)
    return intent_frames


def extract_safety_behavior_from_ws_events(
    ws_events_jsonl_path: Path,
    *,
    critical_frame_seqs: set[int] | None = None,
    near_window_frames: int = 2,
) -> dict[str, Any]:
    normalized_summary = collect_normalized_ws_events(ws_events_jsonl_path)
    normalized_events = normalized_summary.get("events", [])
    if normalized_events:
        return _extract_safety_behavior_from_normalized(
            normalized_events,
            critical_frame_seqs=critical_frame_seqs,
            near_window_frames=near_window_frames,
        )

    return _extract_safety_behavior_legacy(
        ws_events_jsonl_path,
        critical_frame_seqs=critical_frame_seqs,
        near_window_frames=near_window_frames,
    )


def _extract_safety_behavior_from_normalized(
    events: list[dict[str, Any]],
    *,
    critical_frame_seqs: set[int] | None,
    near_window_frames: int,
) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    responses = 0
    timeouts = 0
    response_latencies: list[int] = []
    timeout_frame_samples: list[int] = []
    missing_frame_samples: list[int] = []
    frames_with_intent: set[int] = set()
    latch_count = 0
    preempt_count = 0
    local_fallback_count = 0
    latch_duration_values: list[int] = []
    preempt_duration_values: list[int] = []
    latch_frames: list[int] = []
    preempt_frames: list[int] = []

    for event in events:
        name = str(event.get("name", "")).strip().lower()
        phase = str(event.get("phase", "")).strip().lower()
        status = str(event.get("status", "")).strip().lower()
        seq = _parse_int(event.get("frameSeq"))
        ts_ms = _parse_int(event.get("tsMs")) or 0
        latency = _parse_int(event.get("latencyMs"))
        payload = event.get("payload")
        request_id = str(payload.get("requestId", "")).strip() if isinstance(payload, dict) else ""
        if not request_id:
            request_id = str(payload.get("confirmId", "")).strip() if isinstance(payload, dict) else ""

        if name in {"safety.confirm", "ui.confirm_request", "ui.confirm_response"}:
            timeout_reason = ""
            if isinstance(payload, dict):
                timeout_reason = str(payload.get("reason", "")).strip().lower()
            has_choice_payload = False
            if isinstance(payload, dict):
                has_choice_payload = any(key in payload for key in ("choice", "confirmed", "answer", "yes", "no"))

            is_ui_request = name == "ui.confirm_request"
            is_ui_response = name == "ui.confirm_response"
            is_timeout = status == "timeout" or phase == "error" or "timeout" in timeout_reason or "expired" in timeout_reason
            is_response = (is_ui_response or ((not is_ui_request) and (phase == "result" or has_choice_payload))) and not is_timeout
            # Older events sometimes normalize to safety.confirm without an explicit phase.
            is_request = is_ui_request or (
                not is_response and not is_timeout and (phase == "start" or not phase)
            )
            if is_request:
                if seq is not None:
                    frames_with_intent.add(seq)
                requests.append(
                    {
                        "seq": seq,
                        "timeMs": ts_ms,
                        "requestId": request_id or None,
                        "responded": False,
                        "timedOut": False,
                    }
                )
            if is_response:
                responses += 1
                matched = _match_pending_request(requests, seq=seq, request_id=request_id or None)
                if latency is None and matched is not None:
                    start_ms = _parse_int(matched.get("timeMs"))
                    if start_ms is not None:
                        latency = max(0, ts_ms - start_ms)
                if latency is None and isinstance(payload, dict):
                    payload_latency = _parse_int(payload.get("latencyMs"))
                    if payload_latency is not None and payload_latency >= 0:
                        latency = payload_latency
                if latency is not None and latency >= 0:
                    response_latencies.append(int(latency))
                if matched is not None:
                    matched["responded"] = True
            if is_timeout:
                timeouts += 1
                matched = _match_pending_request(requests, seq=seq, request_id=request_id or None)
                if matched is not None:
                    matched["timedOut"] = True
                    sample_seq = _parse_int(matched.get("seq"))
                    if sample_seq is not None and len(timeout_frame_samples) < 5:
                        timeout_frame_samples.append(sample_seq)
                elif seq is not None and len(timeout_frame_samples) < 5:
                    timeout_frame_samples.append(seq)

        if name == "safety.latch":
            latch_count += 1
            if seq is not None:
                latch_frames.append(seq)
            if latency is not None:
                latch_duration_values.append(latency)

        if name == "safety.preempt":
            preempt_count += 1
            if seq is not None:
                preempt_frames.append(seq)
            if latency is not None:
                preempt_duration_values.append(latency)

        if name == "safety.local_fallback":
            local_fallback_count += 1

    missing_response_count = 0
    for req in requests:
        if not req.get("responded") and not req.get("timedOut"):
            missing_response_count += 1
            sample_seq = _parse_int(req.get("seq"))
            if sample_seq is not None and len(missing_frame_samples) < 5:
                missing_frame_samples.append(sample_seq)

    latency_payload: dict[str, Any] | None
    if response_latencies:
        latency_payload = {
            "count": len(response_latencies),
            "p50": _percentile(response_latencies, 50),
            "p90": _percentile(response_latencies, 90),
            "p99": _percentile(response_latencies, 99),
            "max": max(response_latencies),
        }
    else:
        latency_payload = None

    critical_known = bool(critical_frame_seqs)
    latch_near_critical: int | None = None
    preempt_near_critical: int | None = None
    window = max(0, int(near_window_frames))
    if critical_known:
        latch_near_critical = _count_near_critical_frames(latch_frames, critical_frame_seqs or set(), window)
        preempt_near_critical = _count_near_critical_frames(preempt_frames, critical_frame_seqs or set(), window)

    return {
        "confirm": {
            "requests": len(requests),
            "responses": responses,
            "timeouts": timeouts,
            "latencyMs": latency_payload,
            "missingResponseCount": missing_response_count,
            "framesWithConfirmIntent": len(frames_with_intent),
            "timeoutFrameSeqSample": timeout_frame_samples,
            "missingFrameSeqSample": missing_frame_samples,
        },
        "latch": {
            "count": latch_count,
            "nearCriticalCount": latch_near_critical,
            "durationMs": _build_duration_payload(latch_duration_values),
        },
        "preempt": {
            "count": preempt_count,
            "nearCriticalCount": preempt_near_critical,
            "durationMs": _build_duration_payload(preempt_duration_values),
        },
        "fallback": {
            "localFallbackCount": local_fallback_count,
        },
    }


def _build_duration_payload(values: list[int]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "p50": _percentile(values, 50),
        "p90": _percentile(values, 90),
        "max": max(values),
    }


def _extract_safety_behavior_legacy(
    ws_events_jsonl_path: Path,
    *,
    critical_frame_seqs: set[int] | None = None,
    near_window_frames: int = 2,
) -> dict[str, Any]:
    request_keywords = ["confirm", "ask_user", "user_confirm", "clarify", "double_check"]
    response_keywords = ["confirm_result", "user_response", "confirm_done", "clarify_done"]
    timeout_keywords = ["timeout", "confirm_timeout", "expired"]
    latch_keywords = ["latch", "critical_latch", "safety_lock", "emergency"]
    preempt_keywords = ["preempt", "preemption"]
    fallback_keywords = ["local_fallback", "safety_fallback", "on_device_fallback", "fallback_triggered"]

    requests: list[dict[str, Any]] = []
    responses = 0
    timeouts = 0
    response_latencies: list[int] = []
    timeout_frame_samples: list[int] = []
    missing_frame_samples: list[int] = []
    frames_with_intent: set[int] = set()
    latch_count = 0
    preempt_count = 0
    local_fallback_count = 0
    latch_duration_values: list[int] = []
    preempt_duration_values: list[int] = []
    latch_frames: list[int] = []
    preempt_frames: list[int] = []

    for row in _iter_jsonl(ws_events_jsonl_path):
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            if isinstance(row, dict):
                event = row
            else:
                continue

        seq = _extract_frame_seq(event)
        row_time_ms = _extract_row_time_ms(row, event)
        blob = _event_text_blob(event)
        request_id = _extract_request_id(event)
        has_choice_payload = _has_confirm_choice_payload(event)

        is_confirm_response = _contains_any(blob, response_keywords) or has_choice_payload
        is_confirm_timeout = _contains_any(blob, timeout_keywords)
        is_confirm_request = _contains_any(blob, request_keywords) and not is_confirm_response and not is_confirm_timeout

        if is_confirm_request:
            if seq is not None:
                frames_with_intent.add(seq)
            requests.append(
                {
                    "seq": seq,
                    "timeMs": row_time_ms,
                    "requestId": request_id,
                    "responded": False,
                    "timedOut": False,
                }
            )

        if is_confirm_response:
            responses += 1
            matched = _match_pending_request(requests, seq=seq, request_id=request_id)
            latency = _extract_latency_ms(event)
            if latency is None and matched is not None:
                start_ms = _parse_int(matched.get("timeMs"))
                if start_ms is not None:
                    latency = max(0, row_time_ms - start_ms)
            if latency is not None and latency >= 0:
                response_latencies.append(int(latency))
            if matched is not None:
                matched["responded"] = True

        if is_confirm_timeout:
            timeouts += 1
            matched = _match_pending_request(requests, seq=seq, request_id=request_id)
            if matched is not None:
                matched["timedOut"] = True
                sample_seq = _parse_int(matched.get("seq"))
                if sample_seq is not None and len(timeout_frame_samples) < 5:
                    timeout_frame_samples.append(sample_seq)
            elif seq is not None and len(timeout_frame_samples) < 5:
                timeout_frame_samples.append(seq)

        if _contains_any(blob, latch_keywords):
            latch_count += 1
            if seq is not None:
                latch_frames.append(seq)
            duration = _extract_duration_ms(event)
            if duration is not None:
                latch_duration_values.append(duration)

        if _contains_any(blob, preempt_keywords):
            preempt_count += 1
            if seq is not None:
                preempt_frames.append(seq)
            duration = _extract_duration_ms(event)
            if duration is not None:
                preempt_duration_values.append(duration)

        if _contains_any(blob, fallback_keywords):
            local_fallback_count += 1

    missing_response_count = 0
    for req in requests:
        if not req.get("responded") and not req.get("timedOut"):
            missing_response_count += 1
            sample_seq = _parse_int(req.get("seq"))
            if sample_seq is not None and len(missing_frame_samples) < 5:
                missing_frame_samples.append(sample_seq)

    if response_latencies:
        latency_payload: dict[str, Any] | None = {
            "count": len(response_latencies),
            "p50": _percentile(response_latencies, 50),
            "p90": _percentile(response_latencies, 90),
            "p99": _percentile(response_latencies, 99),
            "max": max(response_latencies),
        }
    else:
        latency_payload = None

    critical_known = bool(critical_frame_seqs)
    latch_near_critical: int | None = None
    preempt_near_critical: int | None = None
    window = max(0, int(near_window_frames))
    if critical_known:
        latch_near_critical = _count_near_critical_frames(latch_frames, critical_frame_seqs or set(), window)
        preempt_near_critical = _count_near_critical_frames(preempt_frames, critical_frame_seqs or set(), window)

    latch_duration_payload: dict[str, Any] | None
    if latch_duration_values:
        latch_duration_payload = {
            "count": len(latch_duration_values),
            "p50": _percentile(latch_duration_values, 50),
            "p90": _percentile(latch_duration_values, 90),
            "max": max(latch_duration_values),
        }
    else:
        latch_duration_payload = None

    preempt_duration_payload: dict[str, Any] | None
    if preempt_duration_values:
        preempt_duration_payload = {
            "count": len(preempt_duration_values),
            "p50": _percentile(preempt_duration_values, 50),
            "p90": _percentile(preempt_duration_values, 90),
            "max": max(preempt_duration_values),
        }
    else:
        preempt_duration_payload = None

    return {
        "confirm": {
            "requests": len(requests),
            "responses": responses,
            "timeouts": timeouts,
            "latencyMs": latency_payload,
            "missingResponseCount": missing_response_count,
            "framesWithConfirmIntent": len(frames_with_intent),
            "timeoutFrameSeqSample": timeout_frame_samples,
            "missingFrameSeqSample": missing_frame_samples,
        },
        "latch": {
            "count": latch_count,
            "nearCriticalCount": latch_near_critical,
            "durationMs": latch_duration_payload,
        },
        "preempt": {
            "count": preempt_count,
            "nearCriticalCount": preempt_near_critical,
            "durationMs": preempt_duration_payload,
        },
        "fallback": {
            "localFallbackCount": local_fallback_count,
        },
    }


def levenshtein(a: Sequence[Any] | str, b: Sequence[Any] | str) -> int:
    if isinstance(a, str):
        a_seq: Sequence[Any] = list(a)
    else:
        a_seq = list(a)
    if isinstance(b, str):
        b_seq: Sequence[Any] = list(b)
    else:
        b_seq = list(b)

    if a_seq == b_seq:
        return 0
    if not a_seq:
        return len(b_seq)
    if not b_seq:
        return len(a_seq)

    prev = list(range(len(b_seq) + 1))
    for i, left in enumerate(a_seq, start=1):
        curr = [i]
        for j, right in enumerate(b_seq, start=1):
            cost = 0 if left == right else 1
            curr.append(
                min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + cost,
                )
            )
        prev = curr
    return prev[-1]


def compute_ocr_metrics(
    gt_map: dict[int, str],
    pred_map: dict[int, dict[str, Any]],
    frames_total: int,
    intent_frames: set[int] | None = None,
) -> dict[str, Any]:
    frames_total_safe = max(0, int(frames_total))
    frames_with_gt = len(gt_map)
    frames_with_pred = len(pred_map)
    coverage = (frames_with_pred / frames_total_safe) if frames_total_safe > 0 else 0.0
    intent_frames_count = len(intent_frames or set())
    intent_coverage = (intent_frames_count / frames_total_safe) if frames_total_safe > 0 else 0.0

    exact_matches = 0
    char_distance = 0
    char_total = 0
    word_distance = 0
    word_total = 0
    latencies: list[int] = []
    frames_with_gt_and_pred = 0
    frames_pred_but_gt_empty = 0
    mismatch_rows: list[dict[str, Any]] = []

    for seq, gt_text in gt_map.items():
        pred_text = str(pred_map.get(seq, {}).get("text", ""))
        if seq in pred_map:
            frames_with_gt_and_pred += 1
        if _normalize_text(gt_text) == _normalize_text(pred_text):
            exact_matches += 1
        elif seq in pred_map:
            mismatch_rows.append(
                {
                    "frameSeq": seq,
                    "gtText": gt_text,
                    "predText": pred_text,
                    "cer": _normalized_distance(list(gt_text or ""), list(pred_text or "")),
                    "wer": _normalized_distance(_tokenize(gt_text), _tokenize(pred_text)),
                }
            )

        gt_chars = list(gt_text or "")
        pred_chars = list(pred_text or "")
        if gt_chars:
            char_distance += levenshtein(gt_chars, pred_chars)
            char_total += len(gt_chars)

        gt_tokens = _tokenize(gt_text)
        pred_tokens = _tokenize(pred_text)
        if gt_tokens:
            word_distance += levenshtein(gt_tokens, pred_tokens)
            word_total += len(gt_tokens)

    for item in pred_map.values():
        latency = item.get("latencyMs")
        if isinstance(latency, (int, float)) and latency >= 0:
            latencies.append(int(latency))

    for seq in pred_map.keys():
        gt_text = gt_map.get(seq, "")
        if not str(gt_text or "").strip():
            frames_pred_but_gt_empty += 1

    mismatch_rows.sort(key=lambda row: (-float(row.get("cer", 0.0)), -float(row.get("wer", 0.0)), int(row.get("frameSeq", 0))))

    metrics: dict[str, Any] = {
        "framesTotal": frames_total_safe,
        "framesWithGt": frames_with_gt,
        "framesWithPred": frames_with_pred,
        "coverage": coverage,
        "resultCoverage": coverage,
        "intentCoverage": intent_coverage,
        "framesWithOcrIntent": intent_frames_count,
        "framesWithGtAndPred": frames_with_gt_and_pred,
        "gtHitRate": _safe_ratio(frames_with_gt_and_pred, frames_with_gt),
        "framesPredButGtEmpty": frames_pred_but_gt_empty,
        "falsePositiveRate": _safe_ratio(frames_pred_but_gt_empty, frames_with_pred),
        "topMismatches": mismatch_rows[:5],
        "exactMatchRate": (exact_matches / frames_with_gt) if frames_with_gt > 0 else 0.0,
        "cer": (char_distance / char_total) if char_total > 0 else 0.0,
        "wer": (word_distance / word_total) if word_total > 0 else 0.0,
    }

    if latencies:
        metrics["latencyMs"] = {
            "count": len(latencies),
            "p50": _percentile(latencies, 50),
            "p90": _percentile(latencies, 90),
            "p99": _percentile(latencies, 99),
            "max": max(latencies),
        }
    else:
        metrics["latencyAvailable"] = False
        metrics["latencyMs"] = None
    return metrics


def compute_depth_risk_metrics(
    gt_map: dict[int, list[dict[str, Any]]],
    pred_map: dict[int, list[dict[str, Any]]],
    window_frames: int,
    *,
    normalization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    window = max(0, int(window_frames))
    by_kind_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    local_norm_meta = _new_hazard_norm_meta()

    pred_entries: list[dict[str, Any]] = []
    pred_entries_by_kind: dict[str, list[int]] = defaultdict(list)
    for seq, hazards in pred_map.items():
        for hazard in hazards:
            normalized_rows, warnings = normalize_hazards([hazard] if isinstance(hazard, dict) else [])
            _ingest_hazard_warnings(local_norm_meta, warnings)
            if not normalized_rows:
                continue
            row = normalized_rows[0]
            kind = _normalize_kind(row.get("hazardKind"))
            if not kind:
                continue
            pred_entries.append({"seq": int(seq), "kind": kind, "used": False})
            pred_entries_by_kind[kind].append(len(pred_entries) - 1)
    for kind, idx_rows in pred_entries_by_kind.items():
        idx_rows.sort(key=lambda item: int(pred_entries[item]["seq"]))

    gt_critical_count = 0
    hit_critical_count = 0
    miss_critical_count = 0
    detection_delays: list[int] = []
    matched_pairs: list[dict[str, Any]] = []
    top_misses: list[dict[str, Any]] = []

    for gt_seq, hazards in gt_map.items():
        for hazard in hazards:
            normalized_rows, warnings = normalize_hazards([hazard] if isinstance(hazard, dict) else [])
            _ingest_hazard_warnings(local_norm_meta, warnings)
            if not normalized_rows:
                continue
            row = normalized_rows[0]
            kind = _normalize_kind(row.get("hazardKind"))
            if not kind:
                continue
            severity = str(row.get("severity", "")).strip().lower()
            is_critical = severity == "critical"
            if is_critical:
                gt_critical_count += 1

            best_idx = -1
            best_pred_seq = 10**9
            best_dist = 10**9
            for idx in pred_entries_by_kind.get(kind, []):
                pred = pred_entries[idx]
                if pred["used"]:
                    continue
                pred_seq = int(pred["seq"])
                dist = abs(pred_seq - int(gt_seq))
                if dist > window:
                    continue
                if pred_seq < best_pred_seq or (pred_seq == best_pred_seq and dist < best_dist):
                    best_pred_seq = pred_seq
                    best_dist = dist
                    best_idx = idx

            if best_idx >= 0:
                pred_entries[best_idx]["used"] = True
                by_kind_counts[kind]["tp"] += 1
                pred_seq = int(pred_entries[best_idx]["seq"])
                delay_raw = pred_seq - int(gt_seq)
                delay = max(0, min(window, delay_raw))
                detection_delays.append(delay)
                matched_pairs.append({"gtSeq": int(gt_seq), "predSeq": pred_seq, "kind": kind, "delay": delay})
                if is_critical:
                    hit_critical_count += 1
            else:
                by_kind_counts[kind]["fn"] += 1
                if len(top_misses) < 5:
                    top_misses.append(
                        {
                            "frameSeq": int(gt_seq),
                            "hazardKind": kind,
                            "severity": severity or None,
                            "window": window,
                            "note": "no_prediction_in_window",
                        }
                    )
                if is_critical:
                    miss_critical_count += 1

    for pred in pred_entries:
        if pred["used"]:
            continue
        by_kind_counts[pred["kind"]]["fp"] += 1

    by_kind: dict[str, dict[str, Any]] = {}
    total_tp = 0
    total_fp = 0
    total_fn = 0
    for kind, counts in sorted(by_kind_counts.items(), key=lambda item: item[0]):
        tp = counts["tp"]
        fp = counts["fp"]
        fn = counts["fn"]
        total_tp += tp
        total_fp += fp
        total_fn += fn
        by_kind[kind] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": _safe_ratio(tp, tp + fp),
            "recall": _safe_ratio(tp, tp + fn),
            "f1": _f1(tp, fp, fn),
        }

    local_norm = _finalize_hazard_norm_meta(local_norm_meta)
    merged_norm = normalization or {"unknownKinds": [], "aliasHits": [], "warningsCount": 0}
    if normalization:
        merged_norm = {
            "unknownKinds": sorted(
                set(str(item) for item in normalization.get("unknownKinds", []))
                | set(str(item) for item in local_norm.get("unknownKinds", []))
            ),
            "aliasHits": _merge_alias_hits(
                normalization.get("aliasHits", []),
                local_norm.get("aliasHits", []),
            ),
            "warningsCount": int(normalization.get("warningsCount", 0) or 0) + int(local_norm.get("warningsCount", 0) or 0),
        }
    else:
        merged_norm = local_norm

    matched_pairs_sorted = sorted(
        matched_pairs,
        key=lambda row: (
            -int(row.get("delay", 0)),
            int(row.get("gtSeq", 0)),
            int(row.get("predSeq", 0)),
            str(row.get("kind", "")),
        ),
    )
    return {
        "matchWindowFrames": window,
        "byKind": by_kind,
        "overall": {
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "precision": _safe_ratio(total_tp, total_tp + total_fp),
            "recall": _safe_ratio(total_tp, total_tp + total_fn),
            "f1": _f1(total_tp, total_fp, total_fn),
        },
        "critical": {
            "gtCriticalCount": gt_critical_count,
            "hitCriticalCount": hit_critical_count,
            "missCriticalCount": miss_critical_count,
        },
        "detectionDelayFrames": {
            "count": len(detection_delays),
            "p50": _percentile(detection_delays, 50),
            "p90": _percentile(detection_delays, 90),
            "max": max(detection_delays) if detection_delays else 0,
            "valuesSample": detection_delays[:10],
        },
        "delayDiagnostics": {
            "matchedPairsSample": sorted(matched_pairs, key=lambda row: (int(row.get("gtSeq", 0)), int(row.get("predSeq", 0))))[:5],
            "maxDelayPairs": matched_pairs_sorted[:5],
        },
        "topMisses": top_misses,
        "normalization": merged_norm,
    }


def compute_seg_metrics(
    gt_map: dict[int, list[dict[str, Any]]],
    pred_map: dict[int, list[dict[str, Any]]],
    pred_event_frames: set[int],
    latencies: list[int],
    frames_total: int,
    *,
    iou_threshold: float = 0.5,
) -> dict[str, Any]:
    frames_total_safe = max(0, int(frames_total))
    frames_with_gt = len([seq for seq, rows in gt_map.items() if isinstance(rows, list) and rows])
    frames_with_pred = len({seq for seq in pred_event_frames if isinstance(seq, int)})
    coverage = _safe_ratio(frames_with_pred, frames_with_gt)

    tp = 0
    fp = 0
    fn = 0
    iou_hits: list[float] = []
    top_misses: list[dict[str, Any]] = []
    top_fp: list[dict[str, Any]] = []
    mask_tp = 0
    mask_fp = 0
    mask_fn = 0
    mask_iou_hits: list[float] = []
    mask_top_misses: list[dict[str, Any]] = []
    mask_top_fp: list[dict[str, Any]] = []
    has_any_mask = False

    all_frames = sorted(set(gt_map.keys()) | set(pred_map.keys()) | set(pred_event_frames))
    threshold = max(0.0, min(1.0, float(iou_threshold)))

    for frame_seq in all_frames:
        gt_rows = [_normalize_seg_object(item) for item in gt_map.get(frame_seq, [])]
        gt_rows = [item for item in gt_rows if isinstance(item, dict)]
        pred_rows = [_normalize_seg_object(item) for item in pred_map.get(frame_seq, [])]
        pred_rows = [item for item in pred_rows if isinstance(item, dict)]
        if any(isinstance(item.get("mask"), dict) for item in gt_rows) or any(
            isinstance(item.get("mask"), dict) for item in pred_rows
        ):
            has_any_mask = True

        matched, unmatched_gt, unmatched_pred = _match_seg_pairs(gt_rows, pred_rows, iou_fn=_seg_pair_bbox_iou)
        for pair in matched:
            iou = float(pair.get("iou", 0.0) or 0.0)
            gt_item = pair.get("gt")
            gt_item = gt_item if isinstance(gt_item, dict) else {}
            pred_item = pair.get("pred")
            pred_item = pred_item if isinstance(pred_item, dict) else {}
            if iou >= threshold:
                tp += 1
                iou_hits.append(iou)
            else:
                fn += 1
                fp += 1
                if len(top_misses) < 5:
                    top_misses.append(
                        {
                            "frameSeq": int(frame_seq),
                            "label": str(gt_item.get("label", "")).strip(),
                            "bbox": gt_item.get("bbox"),
                            "bestIoU": round(iou, 4),
                            "note": "predicted_but_iou_below_threshold",
                        }
                    )
                if len(top_fp) < 5:
                    top_fp.append(
                        {
                            "frameSeq": int(frame_seq),
                            "label": str(pred_item.get("label", "")).strip(),
                            "bbox": pred_item.get("bbox"),
                            "score": pred_item.get("score"),
                            "bestIoU": round(iou, 4),
                            "note": "fp_iou_below_threshold",
                        }
                    )

        mask_matched, mask_unmatched_gt, mask_unmatched_pred = _match_seg_pairs(
            gt_rows,
            pred_rows,
            iou_fn=_seg_pair_mask_or_bbox_iou,
        )
        for pair in mask_matched:
            iou = float(pair.get("iou", 0.0) or 0.0)
            gt_item = pair.get("gt")
            gt_item = gt_item if isinstance(gt_item, dict) else {}
            pred_item = pair.get("pred")
            pred_item = pred_item if isinstance(pred_item, dict) else {}
            if iou >= threshold:
                mask_tp += 1
                mask_iou_hits.append(iou)
            else:
                mask_fn += 1
                mask_fp += 1
                if len(mask_top_misses) < 5:
                    mask_top_misses.append(
                        {
                            "frameSeq": int(frame_seq),
                            "label": str(gt_item.get("label", "")).strip(),
                            "bbox": gt_item.get("bbox"),
                            "bestIoU": round(iou, 4),
                            "metric": "maskIoU",
                            "note": "predicted_but_iou_below_threshold",
                        }
                    )
                if len(mask_top_fp) < 5:
                    mask_top_fp.append(
                        {
                            "frameSeq": int(frame_seq),
                            "label": str(pred_item.get("label", "")).strip(),
                            "bbox": pred_item.get("bbox"),
                            "score": pred_item.get("score"),
                            "bestIoU": round(iou, 4),
                            "metric": "maskIoU",
                            "note": "fp_iou_below_threshold",
                        }
                    )

        for idx in mask_unmatched_gt:
            mask_fn += 1
            if len(mask_top_misses) < 5:
                gt_item = gt_rows[idx]
                mask_top_misses.append(
                    {
                        "frameSeq": int(frame_seq),
                        "label": str(gt_item.get("label", "")).strip(),
                        "bbox": gt_item.get("bbox"),
                        "metric": "maskIoU",
                        "note": "no_prediction_for_gt",
                    }
                )

        for idx in mask_unmatched_pred:
            mask_fp += 1
            if len(mask_top_fp) < 5:
                pred_item = pred_rows[idx]
                mask_top_fp.append(
                    {
                        "frameSeq": int(frame_seq),
                        "label": str(pred_item.get("label", "")).strip(),
                        "bbox": pred_item.get("bbox"),
                        "score": pred_item.get("score"),
                        "metric": "maskIoU",
                        "note": "no_gt_match",
                    }
                )

        for idx in unmatched_gt:
            fn += 1
            if len(top_misses) < 5:
                gt_item = gt_rows[idx]
                top_misses.append(
                    {
                        "frameSeq": int(frame_seq),
                        "label": str(gt_item.get("label", "")).strip(),
                        "bbox": gt_item.get("bbox"),
                        "note": "no_prediction_for_gt",
                    }
                )

        for idx in unmatched_pred:
            fp += 1
            if len(top_fp) < 5:
                pred_item = pred_rows[idx]
                top_fp.append(
                    {
                        "frameSeq": int(frame_seq),
                        "label": str(pred_item.get("label", "")).strip(),
                        "bbox": pred_item.get("bbox"),
                        "score": pred_item.get("score"),
                        "note": "no_gt_match",
                    }
                )

    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    f1 = _f1(tp, fp, fn)
    mean_iou = _safe_ratio(sum(iou_hits), len(iou_hits))
    latency_stats = summarize_latency(latencies)
    mask_precision = _safe_ratio(mask_tp, mask_tp + mask_fp)
    mask_recall = _safe_ratio(mask_tp, mask_tp + mask_fn)
    mask_f1 = _f1(mask_tp, mask_fp, mask_fn)
    mask_mean_iou = _safe_ratio(sum(mask_iou_hits), len(mask_iou_hits))

    payload = {
        "present": bool(gt_map or pred_event_frames),
        "framesTotal": frames_total_safe,
        "framesWithGt": frames_with_gt,
        "framesWithPred": frames_with_pred,
        "coverage": coverage,
        "iouThreshold": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1At50": f1,
        "meanIoU": mean_iou,
        "latencyMs": {
            "count": int(latency_stats.get("count", 0) or 0),
            "p50": int(latency_stats.get("p50", 0) or 0),
            "p90": int(latency_stats.get("p90", 0) or 0),
            "max": int(latency_stats.get("max", 0) or 0),
        },
        "topMisses": top_misses[:5],
        "topFP": top_fp[:5],
    }
    if has_any_mask:
        payload.update(
            {
                "maskMeanIoU": mask_mean_iou,
                "maskPrecision50": mask_precision,
                "maskRecall50": mask_recall,
                "maskF1_50": mask_f1,
                "maskFramesWithGt": frames_with_gt,
                "maskFramesWithPred": frames_with_pred,
                "maskCoverage": coverage,
                "maskTopMisses": mask_top_misses[:5],
                "maskTopFP": mask_top_fp[:5],
            }
        )
    else:
        payload.update(
            {
                "maskMeanIoU": None,
                "maskPrecision50": None,
                "maskRecall50": None,
                "maskF1_50": None,
                "maskFramesWithGt": None,
                "maskFramesWithPred": None,
                "maskCoverage": None,
                "maskTopMisses": [],
                "maskTopFP": [],
            }
        )
    return payload


def compute_depth_metrics(
    gt_map: dict[int, dict[str, Any]],
    pred_map: dict[int, dict[str, Any]],
    pred_event_frames: set[int],
    latencies: list[int],
    frames_total: int,
) -> dict[str, Any]:
    frames_total_safe = max(0, int(frames_total))
    frames_with_gt = len([seq for seq, row in gt_map.items() if isinstance(row, dict) and isinstance(row.get("grid"), dict)])
    frames_with_pred = len({seq for seq in pred_event_frames if isinstance(seq, int)})
    coverage = _safe_ratio(frames_with_pred, frames_with_gt)

    abs_rel_values: list[float] = []
    sq_err_values: list[float] = []
    delta1_hits = 0
    delta1_total = 0
    top_bad_cells: list[dict[str, Any]] = []
    valid_frames = 0
    all_frames = sorted(set(gt_map.keys()) | set(pred_map.keys()) | set(pred_event_frames))

    for frame_seq in all_frames:
        gt_row = gt_map.get(frame_seq)
        gt_row = gt_row if isinstance(gt_row, dict) else {}
        pred_row = pred_map.get(frame_seq)
        pred_row = pred_row if isinstance(pred_row, dict) else {}
        gt_grid = _normalize_depth_grid_object(gt_row.get("grid"))
        pred_grid = _normalize_depth_grid_object(pred_row.get("grid"))
        if not isinstance(gt_grid, dict) or not isinstance(pred_grid, dict):
            continue
        gt_size = gt_grid.get("size")
        pred_size = pred_grid.get("size")
        if not isinstance(gt_size, list) or not isinstance(pred_size, list):
            continue
        if len(gt_size) != 2 or len(pred_size) != 2:
            continue
        if int(gt_size[0]) != int(pred_size[0]) or int(gt_size[1]) != int(pred_size[1]):
            continue
        gt_values = gt_grid.get("values")
        pred_values = pred_grid.get("values")
        if not isinstance(gt_values, list) or not isinstance(pred_values, list):
            continue
        if len(gt_values) != len(pred_values):
            continue

        valid_frames += 1
        gw = int(gt_size[0])
        valid_index_count = 0
        for idx, (gt_raw, pred_raw) in enumerate(zip(gt_values, pred_values)):
            try:
                gt_val = float(gt_raw)
                pred_val = float(pred_raw)
            except Exception:
                continue
            if gt_val <= 0.0:
                continue
            valid_index_count += 1
            abs_rel = abs(pred_val - gt_val) / gt_val
            sq_err = (pred_val - gt_val) ** 2
            abs_rel_values.append(abs_rel)
            sq_err_values.append(sq_err)
            ratio = max((pred_val / gt_val) if gt_val > 0 else float("inf"), (gt_val / pred_val) if pred_val > 0 else float("inf"))
            delta1_total += 1
            if ratio < 1.25:
                delta1_hits += 1
            if len(top_bad_cells) < 8:
                top_bad_cells.append(
                    {
                        "frameSeq": int(frame_seq),
                        "index": int(idx),
                        "x": int(idx % max(1, gw)),
                        "y": int(idx // max(1, gw)),
                        "gt": int(round(gt_val)),
                        "pred": int(round(pred_val)),
                        "absRel": round(abs_rel, 6),
                    }
                )
            else:
                worst_index = min(range(len(top_bad_cells)), key=lambda i: float(top_bad_cells[i].get("absRel", 0.0)))
                if abs_rel > float(top_bad_cells[worst_index].get("absRel", 0.0)):
                    top_bad_cells[worst_index] = {
                        "frameSeq": int(frame_seq),
                        "index": int(idx),
                        "x": int(idx % max(1, gw)),
                        "y": int(idx // max(1, gw)),
                        "gt": int(round(gt_val)),
                        "pred": int(round(pred_val)),
                        "absRel": round(abs_rel, 6),
                    }
        if valid_index_count <= 0:
            valid_frames = max(0, valid_frames - 1)

    top_bad_cells = sorted(top_bad_cells, key=lambda row: -float(row.get("absRel", 0.0)))[:5]
    latency_stats = summarize_latency(latencies)
    rmse = math.sqrt(_safe_ratio(sum(sq_err_values), len(sq_err_values))) if sq_err_values else 0.0

    return {
        "present": bool(gt_map or pred_event_frames),
        "framesTotal": frames_total_safe,
        "framesWithGt": int(frames_with_gt),
        "framesWithPred": int(frames_with_pred),
        "coverage": float(coverage),
        "absRel": float(_safe_ratio(sum(abs_rel_values), len(abs_rel_values))),
        "rmse": float(rmse),
        "delta1": float(_safe_ratio(delta1_hits, delta1_total)),
        "validFrames": int(valid_frames),
        "latencyMs": {
            "count": int(latency_stats.get("count", 0) or 0),
            "p50": int(latency_stats.get("p50", 0) or 0),
            "p90": int(latency_stats.get("p90", 0) or 0),
            "max": int(latency_stats.get("max", 0) or 0),
        },
        "topBadCells": top_bad_cells,
    }


def compute_quality_score(
    safety_score: float,
    ocr_metrics: dict[str, Any] | None,
    risk_metrics: dict[str, Any] | None,
    safety_behavior: dict[str, Any] | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    penalty = 0.0
    breakdown: list[dict[str, Any]] = []

    critical_fn = 0
    critical_fp = 0
    noncritical_fn = 0
    noncritical_fp = 0

    if risk_metrics:
        overall = risk_metrics.get("overall", {})
        critical = risk_metrics.get("critical", {})
        total_fn = int(overall.get("fn", 0) or 0)
        total_fp = int(overall.get("fp", 0) or 0)
        critical_fn = int(critical.get("missCriticalCount", 0) or 0)
        critical_fp = int(critical.get("criticalFp", 0) or 0)
        noncritical_fn = max(0, total_fn - critical_fn)
        noncritical_fp = max(0, total_fp - critical_fp)

        parts = [
            ("critical_fn", critical_fn * 15.0, {"count": critical_fn}),
            ("critical_fp", critical_fp * 5.0, {"count": critical_fp}),
            ("noncritical_fn", noncritical_fn * 3.0, {"count": noncritical_fn}),
            ("noncritical_fp", noncritical_fp * 1.0, {"count": noncritical_fp}),
        ]
        for reason, value, details in parts:
            if value <= 0:
                continue
            penalty += value
            breakdown.append({"reason": reason, "value": value, "details": details})

    if ocr_metrics:
        cer = float(ocr_metrics.get("cer", 0.0) or 0.0)
        exact = float(ocr_metrics.get("exactMatchRate", 0.0) or 0.0)
        if cer > 0.2:
            penalty += 5.0
            breakdown.append({"reason": "ocr_high_cer", "value": 5.0, "details": {"cer": cer}})
        if exact < 0.5:
            penalty += 5.0
            breakdown.append({"reason": "ocr_low_exact_match", "value": 5.0, "details": {"exactMatchRate": exact}})

    if risk_metrics:
        delay_metrics = risk_metrics.get("detectionDelayFrames", {})
        delay_max = int(delay_metrics.get("max", 0) or 0)
        delay_p90 = int(delay_metrics.get("p90", 0) or 0)
        if delay_max >= 2:
            penalty += 5.0
            breakdown.append({"reason": "risk_detection_delay_max", "value": 5.0, "details": {"max": delay_max}})
        if delay_p90 >= 2:
            penalty += 3.0
            breakdown.append({"reason": "risk_detection_delay_p90", "value": 3.0, "details": {"p90": delay_p90}})

    if safety_behavior:
        confirm = safety_behavior.get("confirm", {}) if isinstance(safety_behavior, dict) else {}
        timeouts = int(confirm.get("timeouts", 0) or 0)
        missing = int(confirm.get("missingResponseCount", 0) or 0)
        latency = confirm.get("latencyMs", {})
        latency_p90 = None
        if isinstance(latency, dict):
            latency_p90 = _parse_int(latency.get("p90"))

        if timeouts > 0:
            value = float(timeouts * 4)
            penalty += value
            breakdown.append({"reason": "confirm_timeouts", "value": value, "details": {"count": timeouts}})
        if missing > 0:
            value = float(missing * 2)
            penalty += value
            breakdown.append({"reason": "confirm_missing_response", "value": value, "details": {"count": missing}})
        if latency_p90 is not None and latency_p90 >= 1500:
            penalty += 3.0
            breakdown.append({"reason": "confirm_latency_p90_high", "value": 3.0, "details": {"p90": latency_p90}})

        if risk_metrics:
            critical = risk_metrics.get("critical", {})
            miss_critical = int(critical.get("missCriticalCount", 0) or 0)
            gt_critical = int(critical.get("gtCriticalCount", 0) or 0)
            latch = safety_behavior.get("latch", {}) if isinstance(safety_behavior, dict) else {}
            preempt = safety_behavior.get("preempt", {}) if isinstance(safety_behavior, dict) else {}
            latch_near = latch.get("nearCriticalCount")
            preempt_near = preempt.get("nearCriticalCount")
            latch_value = int(latch_near or 0) if isinstance(latch_near, (int, float)) else 0
            preempt_value = int(preempt_near or 0) if isinstance(preempt_near, (int, float)) else 0
            if gt_critical > 0 and miss_critical > 0 and (latch_value + preempt_value == 0):
                penalty += 10.0
                breakdown.append(
                    {
                        "reason": "miss_critical_without_latch_preempt",
                        "value": 10.0,
                        "details": {"missCriticalCount": miss_critical, "nearCriticalLatch": latch_value, "nearCriticalPreempt": preempt_value},
                    }
                )

    score = max(0.0, min(100.0, float(safety_score) - penalty))
    return round(score, 3), breakdown


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def _extract_frame_seq(obj: Any) -> int | None:
    if not isinstance(obj, dict):
        return None
    direct_candidates = [
        obj.get("frameSeq"),
        obj.get("frame_seq"),
        obj.get("seq"),
        obj.get("image_seq"),
    ]
    for raw in direct_candidates:
        seq = _parse_int(raw)
        if seq is not None and seq > 0:
            return seq

    nested = obj.get("meta")
    if isinstance(nested, dict):
        seq = _extract_frame_seq(nested)
        if seq is not None:
            return seq

    for key in ("frameId", "filename", "path", "image"):
        raw = obj.get(key)
        if isinstance(raw, str):
            match = _FRAME_RE.search(raw)
            if match:
                seq = _parse_int(match.group(1))
                if seq is not None and seq > 0:
                    return seq
    return None


def _extract_latency_ms(obj: dict[str, Any]) -> int | None:
    for key in ("latencyMs", "latency_ms", "durationMs", "duration_ms"):
        value = _parse_int(obj.get(key))
        if value is not None and value >= 0:
            return value
    start_ms = _parse_int(obj.get("startMs"))
    end_ms = _parse_int(obj.get("endMs"))
    if start_ms is not None and end_ms is not None and end_ms >= start_ms:
        return end_ms - start_ms

    start_ts = _parse_timestamp_like(obj.get("startTs") or obj.get("start_ts"))
    end_ts = _parse_timestamp_like(obj.get("endTs") or obj.get("end_ts"))
    if start_ts is not None and end_ts is not None and end_ts >= start_ts:
        return end_ts - start_ts

    payload = obj.get("payload")
    if isinstance(payload, dict):
        return _extract_latency_ms(payload)
    return None


def _extract_duration_ms(obj: dict[str, Any]) -> int | None:
    return _extract_latency_ms(obj)


def _looks_like_ocr_event(event: dict[str, Any]) -> bool:
    probes = [
        str(event.get("type", "")),
        str(event.get("tool", "")),
        str(event.get("toolName", "")),
        str(event.get("source", "")),
        str(event.get("category", "")),
        str(event.get("summary", "")),
    ]
    text_blob = " ".join(probes).lower()
    if any(keyword in text_blob for keyword in ("ocr", "scan_text", "text_reader", "read_text")):
        return True

    if isinstance(event.get("lines"), list):
        return True

    payload = event.get("payload")
    if isinstance(payload, dict):
        if isinstance(payload.get("lines"), list):
            return True
        payload_blob = " ".join(
            str(payload.get(k, "")) for k in ("tool", "toolName", "source", "category", "summary", "type")
        ).lower()
        if any(keyword in payload_blob for keyword in ("ocr", "scan_text", "read_text")):
            return True
    return False


def _looks_like_ocr_intent_event(event: dict[str, Any]) -> bool:
    probes = [
        str(event.get("type", "")),
        str(event.get("name", "")),
        str(event.get("tool", "")),
        str(event.get("toolName", "")),
        str(event.get("source", "")),
        str(event.get("category", "")),
        str(event.get("summary", "")),
        str(event.get("event", "")),
    ]
    payload = event.get("payload")
    if isinstance(payload, dict):
        probes.extend(
            [
                str(payload.get("type", "")),
                str(payload.get("name", "")),
                str(payload.get("tool", "")),
                str(payload.get("toolName", "")),
                str(payload.get("source", "")),
                str(payload.get("category", "")),
                str(payload.get("summary", "")),
            ]
        )
    blob = " ".join(probes).lower()
    if any(token in blob for token in ("ocr", "scan_text", "read_text", "text_reader", "text")):
        return True
    return False


def _extract_ocr_text(event: dict[str, Any]) -> str:
    for key in ("text", "ocrText", "answerText", "summary", "instruction"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    lines = event.get("lines")
    if isinstance(lines, list):
        merged = _merge_line_text(lines)
        if merged:
            return merged

    payload = event.get("payload")
    if isinstance(payload, dict):
        for key in ("text", "ocrText", "answerText", "summary"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        lines = payload.get("lines")
        if isinstance(lines, list):
            merged = _merge_line_text(lines)
            if merged:
                return merged
        result = payload.get("result")
        if isinstance(result, dict):
            return _extract_ocr_text(result)
    return ""


def _merge_line_text(lines: list[Any]) -> str:
    parts: list[str] = []
    for item in lines:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("text", "")).strip()
        else:
            text = ""
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _normalize_seg_object(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    label = str(item.get("label", "")).strip()
    if not label:
        return None
    bbox = item.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        x0, y0, x1, y1 = [float(value) for value in bbox]
    except Exception:
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    score_raw = item.get("score")
    score: float | None = None
    try:
        if score_raw is not None:
            score = float(score_raw)
    except Exception:
        score = None
    row: dict[str, Any] = {"label": label, "bbox": [x0, y0, x1, y1]}
    if score is not None:
        row["score"] = score
    mask = _normalize_seg_mask_object(item.get("mask"))
    if isinstance(mask, dict):
        row["mask"] = mask
    return row


def _normalize_depth_grid_object(grid_raw: Any) -> dict[str, Any] | None:
    if not isinstance(grid_raw, dict):
        return None
    fmt = str(grid_raw.get("format", "")).strip()
    if fmt != "grid_u16_mm_v1":
        return None
    unit = str(grid_raw.get("unit", "")).strip().lower()
    if unit != "mm":
        return None
    size_raw = grid_raw.get("size")
    if not isinstance(size_raw, list) or len(size_raw) != 2:
        return None
    try:
        gw = int(size_raw[0])
        gh = int(size_raw[1])
    except Exception:
        return None
    if gw <= 0 or gh <= 0:
        return None
    values_raw = grid_raw.get("values")
    if not isinstance(values_raw, list):
        return None
    values: list[int] = []
    for item in values_raw:
        try:
            parsed = int(item)
        except Exception:
            return None
        values.append(max(0, min(65535, parsed)))
    if len(values) != gw * gh:
        return None
    return {"format": "grid_u16_mm_v1", "size": [gw, gh], "unit": "mm", "values": values}


def _bbox_iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    denom = area_a + area_b - inter
    if denom <= 0.0:
        return 0.0
    return inter / denom


def _match_seg_pairs(
    gt_rows: list[dict[str, Any]],
    pred_rows: list[dict[str, Any]],
    *,
    iou_fn: Callable[[dict[str, Any], dict[str, Any]], float] | None = None,
) -> tuple[list[dict[str, Any]], set[int], set[int]]:
    remaining_gt = set(range(len(gt_rows)))
    remaining_pred = set(range(len(pred_rows)))
    matched: list[dict[str, Any]] = []
    iou_resolver = iou_fn if callable(iou_fn) else _seg_pair_bbox_iou

    def _take_best(*, label_only: bool) -> tuple[int, int, float] | None:
        best: tuple[int, int, float] | None = None
        for gi in remaining_gt:
            g = gt_rows[gi]
            g_label = str(g.get("label", "")).strip().lower()
            g_bbox = g.get("bbox")
            if not isinstance(g_bbox, list) or len(g_bbox) != 4:
                continue
            for pi in remaining_pred:
                p = pred_rows[pi]
                p_label = str(p.get("label", "")).strip().lower()
                if label_only and g_label != p_label:
                    continue
                p_bbox = p.get("bbox")
                if not isinstance(p_bbox, list) or len(p_bbox) != 4:
                    continue
                iou = float(iou_resolver(g, p))
                if best is None or iou > best[2]:
                    best = (gi, pi, iou)
        return best

    while True:
        best = _take_best(label_only=True)
        if best is None:
            break
        gi, pi, iou = best
        matched.append({"gt": gt_rows[gi], "pred": pred_rows[pi], "iou": iou})
        remaining_gt.discard(gi)
        remaining_pred.discard(pi)

    while True:
        best = _take_best(label_only=False)
        if best is None:
            break
        gi, pi, iou = best
        matched.append({"gt": gt_rows[gi], "pred": pred_rows[pi], "iou": iou})
        remaining_gt.discard(gi)
        remaining_pred.discard(pi)

    return matched, remaining_gt, remaining_pred


def _seg_pair_bbox_iou(gt_row: dict[str, Any], pred_row: dict[str, Any]) -> float:
    gt_bbox = gt_row.get("bbox")
    pred_bbox = pred_row.get("bbox")
    if not isinstance(gt_bbox, list) or len(gt_bbox) != 4:
        return 0.0
    if not isinstance(pred_bbox, list) or len(pred_bbox) != 4:
        return 0.0
    try:
        return _bbox_iou([float(v) for v in gt_bbox], [float(v) for v in pred_bbox])
    except Exception:
        return 0.0


def _seg_pair_mask_or_bbox_iou(gt_row: dict[str, Any], pred_row: dict[str, Any]) -> float:
    gt_mask = gt_row.get("mask")
    pred_mask = pred_row.get("mask")
    if isinstance(gt_mask, dict) and isinstance(pred_mask, dict):
        mask_iou = _mask_iou(gt_mask, pred_mask)
        if mask_iou is not None:
            return mask_iou
    return _seg_pair_bbox_iou(gt_row, pred_row)


def _normalize_seg_mask_object(mask_raw: Any) -> dict[str, Any] | None:
    if not isinstance(mask_raw, dict):
        return None
    fmt = str(mask_raw.get("format", "")).strip()
    if fmt != "rle_v1":
        return None
    size_raw = mask_raw.get("size")
    if not isinstance(size_raw, list) or len(size_raw) != 2:
        return None
    try:
        h = int(size_raw[0])
        w = int(size_raw[1])
    except Exception:
        return None
    if h <= 0 or w <= 0:
        return None
    counts_raw = mask_raw.get("counts")
    if not isinstance(counts_raw, list):
        return None
    counts: list[int] = []
    total = 0
    for value in counts_raw:
        try:
            parsed = int(value)
        except Exception:
            return None
        if parsed < 0:
            return None
        counts.append(parsed)
        total += parsed
    if total != h * w:
        return None
    return {"format": "rle_v1", "size": [h, w], "counts": counts}


def _decode_rle_bits(mask: dict[str, Any]) -> list[int] | None:
    size = mask.get("size")
    counts = mask.get("counts")
    if not isinstance(size, list) or len(size) != 2:
        return None
    if not isinstance(counts, list):
        return None
    try:
        h = int(size[0])
        w = int(size[1])
    except Exception:
        return None
    if h <= 0 or w <= 0:
        return None
    total = h * w
    bits: list[int] = []
    fill = 0
    for value in counts:
        try:
            run_len = int(value)
        except Exception:
            return None
        if run_len < 0:
            return None
        if run_len > 0:
            bits.extend([fill] * run_len)
        fill = 1 - fill
        if len(bits) > total:
            return None
    if len(bits) != total:
        return None
    return bits


def _mask_iou(gt_mask: dict[str, Any], pred_mask: dict[str, Any]) -> float | None:
    gt_size = gt_mask.get("size")
    pred_size = pred_mask.get("size")
    if not isinstance(gt_size, list) or not isinstance(pred_size, list):
        return None
    if len(gt_size) != 2 or len(pred_size) != 2:
        return None
    try:
        if int(gt_size[0]) != int(pred_size[0]) or int(gt_size[1]) != int(pred_size[1]):
            return None
    except Exception:
        return None

    gt_bits = _decode_rle_bits(gt_mask)
    pred_bits = _decode_rle_bits(pred_mask)
    if gt_bits is None or pred_bits is None:
        return None
    if len(gt_bits) != len(pred_bits):
        return None

    inter = 0
    union = 0
    for g_bit, p_bit in zip(gt_bits, pred_bits):
        g_on = int(g_bit) != 0
        p_on = int(p_bit) != 0
        if g_on and p_on:
            inter += 1
        if g_on or p_on:
            union += 1
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


def _new_hazard_norm_meta() -> dict[str, Any]:
    return {
        "warnings": [],
        "unknownKinds": set(),
        "aliasHits": defaultdict(int),
    }


def _ingest_hazard_warnings(meta: dict[str, Any], warnings: list[str]) -> None:
    store = meta.get("warnings")
    if not isinstance(store, list):
        return
    for item in warnings:
        text = str(item or "").strip()
        if not text:
            continue
        store.append(text)
        if text.startswith("unknown_kind:"):
            kind = text.split(":", 1)[1].strip().lower()
            unknown_set = meta.get("unknownKinds")
            if isinstance(unknown_set, set) and kind:
                unknown_set.add(kind)
        elif text.startswith("alias:"):
            payload = text.split(":", 1)[1].strip()
            parts = payload.split("->", 1)
            if len(parts) == 2:
                from_kind = parts[0].strip().lower()
                to_kind = parts[1].strip().lower()
                if from_kind and to_kind:
                    alias_hits = meta.get("aliasHits")
                    if isinstance(alias_hits, defaultdict):
                        alias_hits[(from_kind, to_kind)] += 1


def _finalize_hazard_norm_meta(meta: dict[str, Any]) -> dict[str, Any]:
    alias_hits = meta.get("aliasHits")
    alias_rows: list[dict[str, Any]] = []
    if isinstance(alias_hits, defaultdict):
        for (from_kind, to_kind), count in sorted(alias_hits.items(), key=lambda item: (item[0][0], item[0][1])):
            alias_rows.append({"from": from_kind, "to": to_kind, "count": int(count)})
    unknown_kinds = meta.get("unknownKinds")
    unknown_rows = sorted(str(item) for item in unknown_kinds) if isinstance(unknown_kinds, set) else []
    warnings = meta.get("warnings")
    warnings_count = len(warnings) if isinstance(warnings, list) else 0
    return {
        "unknownKinds": unknown_rows,
        "aliasHits": alias_rows,
        "warningsCount": warnings_count,
    }


def _merge_alias_hits(left: list[Any], right: list[Any]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for source in (left, right):
        if not isinstance(source, list):
            continue
        for row in source:
            if not isinstance(row, dict):
                continue
            from_kind = str(row.get("from", "")).strip().lower()
            to_kind = str(row.get("to", "")).strip().lower()
            if not from_kind or not to_kind:
                continue
            key = (from_kind, to_kind)
            counts[key] = counts.get(key, 0) + int(row.get("count", 0) or 0)
    return [
        {"from": from_kind, "to": to_kind, "count": count}
        for (from_kind, to_kind), count in sorted(counts.items(), key=lambda item: (item[0][0], item[0][1]))
    ]


def _extract_hazards(payload: dict[str, Any], *, norm_meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    hazards: list[dict[str, Any]] = []

    def push(item: dict[str, Any]) -> None:
        normalized, warnings = normalize_hazards([item])
        if norm_meta is not None:
            _ingest_hazard_warnings(norm_meta, warnings)
        if not normalized:
            return
        row = dict(normalized[0])
        hazards.append(row)

    if isinstance(payload.get("hazardKind"), str):
        push(payload)

    for key in ("hazards", "risks", "depthHazards"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    push(item)

    for key in ("payload", "result", "output"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            hazards.extend(_extract_hazards(nested, norm_meta=norm_meta))
    return hazards


def _normalize_kind(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    kind, _warnings = normalize_hazard_kind(value)
    return kind


def _read_text(payload: dict[str, Any]) -> str:
    for key in ("text", "summary", "label", "value"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _parse_int(value: Any) -> int | None:
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


def _tokenize(text: str) -> list[str]:
    return [token for token in str(text or "").strip().split() if token]


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().split()).lower()


def _safe_ratio(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return num / den


def _to_unit_float(value: Any) -> float:
    try:
        if value is None or isinstance(value, bool):
            return 0.0
        parsed = float(value)
    except Exception:
        return 0.0
    if parsed < 0.0:
        return 0.0
    if parsed > 1.0:
        return 1.0
    return parsed


def _mean_float(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values)) / float(len(values))


def _percentile_float(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(1.0, p / 100.0))
    idx = int(math.ceil(rank * len(ordered)) - 1)
    idx = max(0, min(len(ordered) - 1, idx))
    return float(ordered[idx])


def _f1(tp: int, fp: int, fn: int) -> float:
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    if precision <= 0.0 and recall <= 0.0:
        return 0.0
    return (2.0 * precision * recall) / (precision + recall)


def _percentile(values: list[int], p: int) -> int:
    if not values:
        return 0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(0.0, min(1.0, p / 100.0))
    idx = int(math.ceil(rank * len(sorted_values)) - 1)
    idx = max(0, min(len(sorted_values) - 1, idx))
    return sorted_values[idx]


def _normalized_distance(left: Sequence[Any], right: Sequence[Any]) -> float:
    den = len(left)
    if den <= 0:
        return 0.0
    return levenshtein(left, right) / den


def _contains_any(blob: str, keywords: list[str]) -> bool:
    lowered = str(blob or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _event_text_blob(event: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("type", "name", "tool", "toolName", "source", "category", "summary", "status", "message", "event"):
        value = event.get(key)
        if value is not None:
            parts.append(str(value))
    payload = event.get("payload")
    if isinstance(payload, dict):
        for key in ("type", "name", "tool", "toolName", "source", "category", "summary", "status", "message", "event", "error"):
            value = payload.get(key)
            if value is not None:
                parts.append(str(value))
    return " ".join(parts).lower()


def _extract_request_id(event: dict[str, Any]) -> str | None:
    for key in ("requestId", "confirmId", "id"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    payload = event.get("payload")
    if isinstance(payload, dict):
        for key in ("requestId", "confirmId", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _has_confirm_choice_payload(event: dict[str, Any]) -> bool:
    payload = event.get("payload")
    nodes: list[Any] = [event, payload]
    while nodes:
        node = nodes.pop()
        if not isinstance(node, dict):
            continue
        for key in ("choice", "confirmed", "answer"):
            if key in node:
                return True
        for key in ("yes", "no"):
            value = node.get(key)
            if isinstance(value, bool):
                return True
        for nested_key in ("payload", "result"):
            nested = node.get(nested_key)
            if isinstance(nested, dict):
                nodes.append(nested)
    return False


def _extract_row_time_ms(row: dict[str, Any], event: dict[str, Any]) -> int:
    recv = _parse_timestamp_like(row.get("receivedAtMs"))
    if recv is not None:
        return recv
    ts = _parse_timestamp_like(event.get("timestampMs") or event.get("tsEmitMs") or event.get("ts"))
    if ts is not None:
        return ts
    return 0


def _parse_timestamp_like(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            raw = float(text)
        except ValueError:
            return None
    else:
        return None

    if raw <= 0:
        return None
    # interpret small values as seconds
    if raw < 10_000_000_000:
        raw *= 1000.0
    return int(raw)


def _match_pending_request(
    requests: list[dict[str, Any]],
    *,
    seq: int | None,
    request_id: str | None,
) -> dict[str, Any] | None:
    # 1) requestId exact
    if request_id:
        for item in requests:
            if item.get("responded") or item.get("timedOut"):
                continue
            if item.get("requestId") == request_id:
                return item

    # 2) frame sequence
    if seq is not None:
        for item in requests:
            if item.get("responded") or item.get("timedOut"):
                continue
            if _parse_int(item.get("seq")) == seq:
                return item

    # 3) first unmatched
    for item in requests:
        if item.get("responded") or item.get("timedOut"):
            continue
        return item
    return None


def _count_near_critical_frames(event_frames: list[int], critical_frames: set[int], window: int) -> int:
    total = 0
    for seq in event_frames:
        if any(abs(int(seq) - int(cseq)) <= window for cseq in critical_frames):
            total += 1
    return total


def extract_event_schema_stats(ws_events_jsonl_path: Path) -> dict[str, Any]:
    summary = collect_normalized_ws_events(ws_events_jsonl_path)
    return {
        "version": "byes.event.v1",
        "normalizedEvents": int(summary.get("normalizedEvents", 0) or 0),
        "droppedEvents": int(summary.get("droppedEvents", 0) or 0),
        "warningsCount": int(summary.get("warningsCount", 0) or 0),
    }


def extract_inference_summary_from_ws_events(ws_events_jsonl_path: Path) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {
        "ocr": {"backend": None, "model": None, "endpoint": None},
        "risk": {"backend": None, "model": None, "endpoint": None},
        "seg": {"backend": None, "model": None, "endpoint": None},
        "depth": {"backend": None, "model": None, "endpoint": None},
    }

    normalized_summary = collect_normalized_ws_events(ws_events_jsonl_path)
    normalized_events = normalized_summary.get("events", [])
    for event in normalized_events:
        if not isinstance(event, dict):
            continue
        name = str(event.get("name", "")).strip().lower()
        if name == "ocr.scan_text":
            bucket = summary["ocr"]
        elif name in {"risk.hazards", "risk.depth"}:
            bucket = summary["risk"]
        elif name == "seg.segment":
            bucket = summary["seg"]
        elif name == "depth.estimate":
            bucket = summary["depth"]
        elif name == "seg.prompt":
            payload = event.get("payload")
            if isinstance(payload, dict):
                _merge_seg_prompt_fields(summary["seg"], payload)
            continue
        else:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        _merge_inference_fields(bucket, payload)
    _finalize_seg_prompt_bucket(summary["seg"])

    if _has_any_inference(summary):
        return summary

    for row in _iter_jsonl(ws_events_jsonl_path):
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            if isinstance(row, dict):
                event = row
            else:
                continue
        blob = _event_text_blob(event)
        if "ocr" in blob or "scan_text" in blob:
            _merge_inference_fields(summary["ocr"], event.get("payload") if isinstance(event.get("payload"), dict) else event)
        if "risk" in blob or "hazard" in blob or "depth" in blob:
            _merge_inference_fields(summary["risk"], event.get("payload") if isinstance(event.get("payload"), dict) else event)
        if "seg.prompt" in blob and isinstance(event.get("payload"), dict):
            _merge_seg_prompt_fields(summary["seg"], event.get("payload"))
        if "seg" in blob or "segment" in blob:
            _merge_inference_fields(summary["seg"], event.get("payload") if isinstance(event.get("payload"), dict) else event)
        if "depth" in blob and "risk.depth" not in blob:
            _merge_inference_fields(summary["depth"], event.get("payload") if isinstance(event.get("payload"), dict) else event)

    _finalize_seg_prompt_bucket(summary["seg"])
    return summary


def infer_inference_summary_from_events_v1(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {
        "ocr": {"backend": None, "model": None, "endpoint": None},
        "risk": {"backend": None, "model": None, "endpoint": None},
        "seg": {"backend": None, "model": None, "endpoint": None},
        "depth": {"backend": None, "model": None, "endpoint": None},
    }
    for row in events:
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("category", "")).strip().lower() != "tool":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue

        name = str(event.get("name", "")).strip().lower()
        if name == "ocr.scan_text":
            bucket = summary["ocr"]
        elif name == "risk.hazards":
            bucket = summary["risk"]
        elif name == "seg.segment":
            bucket = summary["seg"]
        elif name == "depth.estimate":
            bucket = summary["depth"]
        elif name == "seg.prompt":
            payload = event.get("payload")
            if isinstance(payload, dict):
                _merge_seg_prompt_fields(summary["seg"], payload)
            continue
        else:
            continue

        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        _merge_inference_fields(bucket, payload)
    _finalize_seg_prompt_bucket(summary["seg"])
    return summary


def extract_seg_prompt_summary_from_events_v1(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    summary = infer_inference_summary_from_events_v1(events).get("seg", {})
    summary = summary if isinstance(summary, dict) else {}
    present = bool(summary.get("promptPresent"))
    total_items_in = int(summary.get("promptTargetsInTotal", 0) or 0) + int(summary.get("promptBoxesInTotal", 0) or 0) + int(
        summary.get("promptPointsInTotal", 0) or 0
    )
    total_items_dropped = int(summary.get("promptTargetsDroppedTotal", 0) or 0) + int(
        summary.get("promptBoxesDroppedTotal", 0) or 0
    ) + int(summary.get("promptPointsDroppedTotal", 0) or 0)
    text_in_total = int(summary.get("promptTextInCharsTotal", 0) or 0)
    text_dropped_total = int(summary.get("promptTextCharsDroppedTotal", 0) or 0)
    truncation_rate = 0.0
    if total_items_in > 0:
        truncation_rate = float(total_items_dropped) / float(total_items_in)
    elif text_in_total > 0:
        truncation_rate = float(text_dropped_total) / float(text_in_total)
    if not present:
        return {
            "present": False,
            "events": 0,
            "targetsCountTotal": 0,
            "textCharsTotal": 0,
            "boxesTotal": 0,
            "pointsTotal": 0,
            "promptVersion": None,
            "promptVersionDiversityCount": 0,
            "budget": {
                "maxChars": 0,
                "maxTargets": 0,
                "maxBoxes": 0,
                "maxPoints": 0,
                "mode": None,
                "textCharsTotal": 0,
                "boxesTotal": 0,
                "pointsTotal": 0,
            },
            "out": {
                "targetsCountTotal": 0,
                "textCharsTotal": 0,
                "boxesTotal": 0,
                "pointsTotal": 0,
                "charsTotal": 0,
            },
            "truncation": {
                "targetsDropped": 0,
                "boxesDropped": 0,
                "pointsDropped": 0,
                "textCharsDropped": 0,
            },
            "complexity": {
                "eventsWithTargets": 0,
                "eventsWithText": 0,
                "eventsWithBoxes": 0,
                "eventsWithPoints": 0,
                "scoreMean": 0.0,
            },
            "packed": {"trueCount": 0, "falseCount": 0},
            "warningsCount": 0,
            "truncationRate": 0.0,
        }
    text_chars = int(summary.get("promptTextCharsTotal", 0) or 0)
    boxes_total = int(summary.get("promptBoxesTotal", 0) or 0)
    points_total = int(summary.get("promptPointsTotal", 0) or 0)
    return {
        "present": True,
        "events": int(summary.get("promptEventCount", 0) or 0),
        "targetsCountTotal": int(summary.get("promptTargetsTotal", 0) or 0),
        "textCharsTotal": text_chars,
        "boxesTotal": boxes_total,
        "pointsTotal": points_total,
        "promptVersion": summary.get("promptVersion"),
        "promptVersionDiversityCount": int(summary.get("promptVersionDiversityCount", 0) or 0),
        "budget": {
            "maxChars": int(summary.get("promptBudgetMaxChars", 0) or 0),
            "maxTargets": int(summary.get("promptBudgetMaxTargets", 0) or 0),
            "maxBoxes": int(summary.get("promptBudgetMaxBoxes", 0) or 0),
            "maxPoints": int(summary.get("promptBudgetMaxPoints", 0) or 0),
            "mode": summary.get("promptBudgetMode"),
            "textCharsTotal": text_chars,
            "boxesTotal": boxes_total,
            "pointsTotal": points_total,
        },
        "out": {
            "targetsCountTotal": int(summary.get("promptTargetsOutTotal", summary.get("promptTargetsTotal", 0)) or 0),
            "textCharsTotal": int(summary.get("promptTextOutCharsTotal", summary.get("promptTextCharsTotal", 0)) or 0),
            "boxesTotal": int(summary.get("promptBoxesOutTotal", summary.get("promptBoxesTotal", 0)) or 0),
            "pointsTotal": int(summary.get("promptPointsOutTotal", summary.get("promptPointsTotal", 0)) or 0),
            "charsTotal": int(summary.get("promptCharsOutTotal", 0) or 0),
        },
        "truncation": {
            "targetsDropped": int(summary.get("promptTargetsDroppedTotal", 0) or 0),
            "boxesDropped": int(summary.get("promptBoxesDroppedTotal", 0) or 0),
            "pointsDropped": int(summary.get("promptPointsDroppedTotal", 0) or 0),
            "textCharsDropped": int(summary.get("promptTextCharsDroppedTotal", 0) or 0),
        },
        "complexity": {
            "eventsWithTargets": int(summary.get("promptComplexityHasTargetsCount", 0) or 0),
            "eventsWithText": int(summary.get("promptComplexityHasTextCount", 0) or 0),
            "eventsWithBoxes": int(summary.get("promptComplexityHasBoxesCount", 0) or 0),
            "eventsWithPoints": int(summary.get("promptComplexityHasPointsCount", 0) or 0),
            "scoreMean": float(summary.get("promptComplexityScoreMean", 0.0) or 0.0),
        },
        "packed": {
            "trueCount": int(summary.get("promptPackedTrueCount", 0) or 0),
            "falseCount": int(summary.get("promptPackedFalseCount", 0) or 0),
        },
        "warningsCount": int(summary.get("promptWarningsCountTotal", 0) or 0),
        "truncationRate": round(max(0.0, min(1.0, truncation_rate)), 6),
    }


def extract_plan_request_summary_from_events_v1(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    event_count = 0
    seg_included_count = 0
    pov_included_count = 0
    fallback_used_count = 0
    seg_chars_values: list[int] = []
    pov_chars_values: list[int] = []
    seg_trunc_segments_dropped_total = 0
    for row in events:
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("name", "")).strip().lower() != "plan.request":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        event_count += 1
        if bool(payload.get("segIncluded")):
            seg_included_count += 1
        if bool(payload.get("povIncluded")):
            pov_included_count += 1
        if isinstance(payload.get("fallbackUsed"), bool) and bool(payload.get("fallbackUsed")):
            fallback_used_count += 1
        seg_chars = _to_nonnegative_int(payload.get("segChars"))
        pov_chars = _to_nonnegative_int(payload.get("povChars"))
        seg_chars_values.append(seg_chars)
        pov_chars_values.append(pov_chars)
        seg_trunc_segments_dropped_total += _to_nonnegative_int(payload.get("segTruncSegmentsDropped"))

    seg_stats = summarize_latency(seg_chars_values)
    pov_stats = summarize_latency(pov_chars_values)
    present = event_count > 0
    return {
        "present": present,
        "events": int(event_count),
        "segIncludedCount": int(seg_included_count),
        "povIncludedCount": int(pov_included_count),
        "segCharsTotal": int(sum(seg_chars_values)),
        "segCharsP90": int(seg_stats.get("p90", 0) or 0),
        "segTruncSegmentsDroppedTotal": int(seg_trunc_segments_dropped_total),
        "povCharsTotal": int(sum(pov_chars_values)),
        "povCharsP90": int(pov_stats.get("p90", 0) or 0),
        "fallbackUsedCount": int(fallback_used_count),
    }


def extract_plan_rule_summary_from_events_v1(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    count = 0
    hints: Counter[str] = Counter()
    for row in events:
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("name", "")).strip().lower() != "plan.rule_applied":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        hint = str(payload.get("hazardHint", "")).strip().lower()
        count += 1
        if hint:
            hints[hint] += 1
    top_hint = hints.most_common(1)[0][0] if hints else None
    return {
        "present": count > 0,
        "ruleAppliedCount": int(count),
        "ruleHazardHintTop": top_hint,
    }


def extract_plan_context_summary_from_events_v1(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    event_count = 0
    context_used_count = 0
    seg_hit_count = 0
    pov_hit_count = 0
    seg_coverages: list[float] = []
    pov_coverages: list[float] = []

    for row in events:
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("name", "")).strip().lower() != "plan.context_alignment":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        seg = payload.get("seg")
        seg = seg if isinstance(seg, dict) else {}
        pov = payload.get("pov")
        pov = pov if isinstance(pov, dict) else {}

        event_count += 1
        if bool(payload.get("contextUsed")):
            context_used_count += 1
        if bool(seg.get("hit")):
            seg_hit_count += 1
        if bool(pov.get("hit")):
            pov_hit_count += 1
        seg_coverages.append(_to_unit_float(seg.get("coverage")))
        pov_coverages.append(_to_unit_float(pov.get("coverage")))

    if event_count <= 0:
        return {
            "present": False,
            "events": 0,
            "contextUsedRate": 0.0,
            "seg": {"hitRate": 0.0, "coverageMean": 0.0, "coverageP90": 0.0},
            "pov": {"hitRate": 0.0, "coverageMean": 0.0, "coverageP90": 0.0},
        }

    return {
        "present": True,
        "events": int(event_count),
        "contextUsedRate": round(_safe_ratio(context_used_count, event_count), 6),
        "seg": {
            "hitRate": round(_safe_ratio(seg_hit_count, event_count), 6),
            "coverageMean": round(_mean_float(seg_coverages), 6),
            "coverageP90": round(_percentile_float(seg_coverages, 90), 6),
        },
        "pov": {
            "hitRate": round(_safe_ratio(pov_hit_count, event_count), 6),
            "coverageMean": round(_mean_float(pov_coverages), 6),
            "coverageP90": round(_percentile_float(pov_coverages, 90), 6),
        },
    }


def extract_plan_context_pack_summary_from_events_v1(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    event_count = 0
    chars_values: list[int] = []
    seg_chars_values: list[int] = []
    pov_chars_values: list[int] = []
    risk_chars_values: list[int] = []
    chars_dropped_total = 0
    mode_counter: Counter[str] = Counter()
    budget_chars_counter: Counter[int] = Counter()

    for row in events:
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("name", "")).strip().lower() != "plan.context_pack":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        stats = payload.get("stats")
        stats = stats if isinstance(stats, dict) else {}
        out_stats = stats.get("out")
        out_stats = out_stats if isinstance(out_stats, dict) else {}
        truncation = stats.get("truncation")
        truncation = truncation if isinstance(truncation, dict) else {}
        budget = payload.get("budget")
        budget = budget if isinstance(budget, dict) else {}

        event_count += 1
        chars_values.append(_to_nonnegative_int(out_stats.get("charsTotal")))
        seg_chars_values.append(_to_nonnegative_int(out_stats.get("segChars")))
        pov_chars_values.append(_to_nonnegative_int(out_stats.get("povChars")))
        risk_chars_values.append(_to_nonnegative_int(out_stats.get("riskChars")))
        chars_dropped_total += _to_nonnegative_int(truncation.get("charsDropped"))
        mode = str(budget.get("mode", "")).strip()
        if mode:
            mode_counter[mode] += 1
        budget_chars = _to_nonnegative_int(budget.get("maxChars"))
        if budget_chars > 0:
            budget_chars_counter[budget_chars] += 1

    if event_count <= 0:
        return {
            "present": False,
            "events": 0,
            "budgetDefault": {"maxChars": 0, "mode": None},
            "out": {
                "charsTotalP90": 0,
                "segCharsP90": 0,
                "povCharsP90": 0,
                "riskCharsP90": 0,
            },
            "truncation": {
                "charsDroppedTotal": 0,
                "truncationRate": 0.0,
            },
            "modeDiversityCount": 0,
        }

    chars_stats = summarize_latency(chars_values)
    seg_stats = summarize_latency(seg_chars_values)
    pov_stats = summarize_latency(pov_chars_values)
    risk_stats = summarize_latency(risk_chars_values)
    truncation_rate = _safe_ratio(chars_dropped_total, max(1, sum(chars_values) + chars_dropped_total))
    top_mode = mode_counter.most_common(1)[0][0] if mode_counter else None
    top_budget_chars = budget_chars_counter.most_common(1)[0][0] if budget_chars_counter else 0
    return {
        "present": True,
        "events": int(event_count),
        "budgetDefault": {
            "maxChars": int(top_budget_chars),
            "mode": top_mode,
        },
        "out": {
            "charsTotalP90": int(chars_stats.get("p90", 0) or 0),
            "segCharsP90": int(seg_stats.get("p90", 0) or 0),
            "povCharsP90": int(pov_stats.get("p90", 0) or 0),
            "riskCharsP90": int(risk_stats.get("p90", 0) or 0),
        },
        "truncation": {
            "charsDroppedTotal": int(chars_dropped_total),
            "truncationRate": round(max(0.0, min(1.0, truncation_rate)), 6),
        },
        "modeDiversityCount": int(len(mode_counter)),
    }


def extract_frame_e2e_summary_from_events_v1(
    events: Iterable[dict[str, Any]],
    *,
    frames_total_declared: int | None = None,
) -> dict[str, Any]:
    deduped_by_key: dict[tuple[str, int], tuple[int, int, dict[str, Any], dict[str, Any]]] = {}
    raw_event_count = 0
    total_ms_values: list[int] = []
    part_values: dict[str, list[int]] = {
        "segMs": [],
        "riskMs": [],
        "planMs": [],
        "executeMs": [],
        "confirmMs": [],
    }
    for index, row in enumerate(events):
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("name", "")).strip().lower() != "frame.e2e":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        raw_event_count += 1
        run_id = str(payload.get("runId", "")).strip() or str(event.get("runId", "")).strip() or "unknown-run"
        seq = _to_nonnegative_int(payload.get("frameSeq"))
        if seq is None:
            seq = _to_nonnegative_int(event.get("frameSeq"))
        if seq is None or seq <= 0:
            continue
        ts_ms = _to_nonnegative_int(event.get("tsMs"))
        if ts_ms is None:
            ts_ms = _to_nonnegative_int(payload.get("t1Ms"))
        if ts_ms is None:
            ts_ms = index
        key = (run_id, int(seq))
        previous = deduped_by_key.get(key)
        if previous is None or (ts_ms, index) >= (previous[0], previous[1]):
            deduped_by_key[key] = (int(ts_ms), int(index), event, payload)

    deduped_events = list(deduped_by_key.values())
    event_count = len(deduped_events)
    duplicates_dropped = int(max(0, raw_event_count - event_count))
    frame_seq_set: set[tuple[str, int]] = set()
    parts_sum_gt_total_count = 0
    for _ts_ms, _idx, event, payload in deduped_events:
        seq = _to_nonnegative_int(payload.get("frameSeq"))
        if seq is None:
            seq = _to_nonnegative_int(event.get("frameSeq"))
        run_id = str(payload.get("runId", "")).strip() or str(event.get("runId", "")).strip() or "unknown-run"
        if seq is not None and seq > 0:
            frame_seq_set.add((run_id, int(seq)))
        total_ms = _to_nonnegative_int(payload.get("totalMs"))
        if total_ms is not None:
            total_ms_values.append(int(total_ms))
        parts = payload.get("partsMs")
        parts = parts if isinstance(parts, dict) else {}
        parts_sum = 0
        parts_non_null = 0
        for key in ("segMs", "riskMs", "planMs", "executeMs", "confirmMs"):
            value = _to_nonnegative_int(parts.get(key))
            if value is not None:
                part_values[key].append(int(value))
                parts_sum += int(value)
                parts_non_null += 1
        if total_ms is not None and parts_non_null > 0 and parts_sum > int(total_ms):
            parts_sum_gt_total_count += 1

    if event_count <= 0:
        return {
            "present": False,
            "events": 0,
            "duplicatesDropped": 0,
            "partsSumGtTotalCount": 0,
            "coverage": {
                "framesWithE2E": 0,
                "framesTotalDeclared": int(max(0, int(frames_total_declared or 0))) if frames_total_declared is not None else None,
                "ratio": 0.0 if frames_total_declared is not None and int(frames_total_declared or 0) > 0 else None,
            },
            "totalMs": summarize_latency([]),
            "partsMs": {
                key: summarize_latency([])
                for key in ("segMs", "riskMs", "planMs", "executeMs", "confirmMs")
            },
        }

    frames_with_e2e = len(frame_seq_set) if frame_seq_set else int(event_count)
    total_declared = None
    coverage_ratio = None
    if frames_total_declared is not None:
        total_declared = int(max(0, int(frames_total_declared or 0)))
        if total_declared > 0:
            coverage_ratio = round(_safe_ratio(frames_with_e2e, total_declared), 6)

    return {
        "present": True,
        "events": int(event_count),
        "duplicatesDropped": int(duplicates_dropped),
        "partsSumGtTotalCount": int(parts_sum_gt_total_count),
        "coverage": {
            "framesWithE2E": int(frames_with_e2e),
            "framesTotalDeclared": total_declared,
            "ratio": coverage_ratio,
        },
        "totalMs": summarize_latency(total_ms_values),
        "partsMs": {
            key: summarize_latency(values)
            for key, values in part_values.items()
        },
    }


def extract_frame_user_e2e_summary_from_events_v1(
    events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    input_frames: set[tuple[str, int]] = set()
    ack_frames: set[tuple[str, int]] = set()
    ack_frames_by_kind: defaultdict[str, set[tuple[str, int]]] = defaultdict(set)
    ack_kind_latest: dict[tuple[str, int, str], tuple[int, int]] = {}
    deduped_by_key: dict[tuple[str, int], tuple[int, int, dict[str, Any], dict[str, Any]]] = {}
    raw_event_count = 0

    for index, row in enumerate(events):
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        name = str(event.get("name", "")).strip().lower()
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        run_id = str(payload.get("runId", "")).strip() or str(event.get("runId", "")).strip() or "unknown-run"
        seq = _to_nonnegative_int(payload.get("frameSeq"))
        if seq is None:
            seq = _to_nonnegative_int(event.get("frameSeq"))
        if seq is None or seq <= 0:
            continue
        key = (run_id, int(seq))
        if name == "frame.input":
            input_frames.add(key)
            continue
        if name == "frame.ack":
            ack_frames.add(key)
            ack_kind = _normalize_frame_ack_kind(payload.get("kind"))
            ack_key = (run_id, int(seq), ack_kind)
            ts_ms = _to_nonnegative_int(event.get("tsMs"))
            if ts_ms is None:
                ts_ms = _to_nonnegative_int(payload.get("feedbackTsMs"))
            if ts_ms is None:
                ts_ms = index
            previous_ack = ack_kind_latest.get(ack_key)
            if previous_ack is None or (int(ts_ms), int(index)) >= (previous_ack[0], previous_ack[1]):
                ack_kind_latest[ack_key] = (int(ts_ms), int(index))
            continue
        if name != "frame.user_e2e":
            continue
        raw_event_count += 1
        ts_ms = _to_nonnegative_int(event.get("tsMs"))
        if ts_ms is None:
            ts_ms = _to_nonnegative_int(payload.get("t1Ms"))
        if ts_ms is None:
            ts_ms = index
        previous = deduped_by_key.get(key)
        if previous is None or (ts_ms, index) >= (previous[0], previous[1]):
            deduped_by_key[key] = (int(ts_ms), int(index), event, payload)

    deduped_events = list(deduped_by_key.values())
    event_count = len(deduped_events)
    duplicates_dropped = int(max(0, raw_event_count - event_count))
    total_values: list[int] = []
    totals_by_frame: dict[tuple[str, int], int] = {}
    for _ts_ms, _idx, _event, payload in deduped_events:
        total_ms = _to_nonnegative_int(payload.get("totalMs"))
        if total_ms is not None:
            total_values.append(int(total_ms))
            frame_run_id = str(payload.get("runId", "")).strip() or str(_event.get("runId", "")).strip() or "unknown-run"
            frame_seq = _to_nonnegative_int(payload.get("frameSeq"))
            if frame_seq is None:
                frame_seq = _to_nonnegative_int(_event.get("frameSeq"))
            if frame_seq is not None and frame_seq > 0:
                totals_by_frame[(frame_run_id, int(frame_seq))] = int(total_ms)

    for run_id, frame_seq, ack_kind in ack_kind_latest.keys():
        ack_frames_by_kind[ack_kind].add((run_id, frame_seq))

    frames_with_input = len(input_frames)
    frames_with_ack = len(ack_frames)
    coverage_ratio = None
    if frames_with_input > 0:
        coverage_ratio = round(_safe_ratio(frames_with_ack, frames_with_input), 6)

    if event_count <= 0:
        return {
            "present": False,
            "events": 0,
            "duplicatesDropped": 0,
            "coverage": {
                "framesWithInputDeclared": int(frames_with_input),
                "framesWithAck": int(frames_with_ack),
                "ratio": coverage_ratio,
            },
            "totalMs": summarize_latency([]),
            "byKind": {},
            "tts": {
                "count": 0,
                "coverageRatio": 0.0 if frames_with_input > 0 else None,
                "p50": 0,
                "p90": 0,
                "max": 0,
            },
        }

    by_kind: dict[str, Any] = {}
    for kind, frames in sorted(ack_frames_by_kind.items()):
        kind_values = [totals_by_frame[key] for key in sorted(frames) if key in totals_by_frame]
        kind_cov = None
        if frames_with_input > 0:
            kind_cov = round(_safe_ratio(len(frames), frames_with_input), 6)
        by_kind[kind] = {
            "count": int(len(kind_values)),
            "coverageRatio": kind_cov,
            "totalMs": summarize_latency(kind_values),
        }

    tts_bucket = by_kind.get("tts")
    if isinstance(tts_bucket, dict):
        tts_total = tts_bucket.get("totalMs")
        tts_total = tts_total if isinstance(tts_total, dict) else {}
        tts_summary = {
            "count": int(tts_total.get("count", 0) or 0),
            "coverageRatio": tts_bucket.get("coverageRatio"),
            "p50": int(tts_total.get("p50", 0) or 0),
            "p90": int(tts_total.get("p90", 0) or 0),
            "max": int(tts_total.get("max", 0) or 0),
        }
    else:
        tts_summary = {
            "count": 0,
            "coverageRatio": 0.0 if frames_with_input > 0 else None,
            "p50": 0,
            "p90": 0,
            "max": 0,
        }

    return {
        "present": True,
        "events": int(event_count),
        "duplicatesDropped": int(duplicates_dropped),
        "coverage": {
            "framesWithInputDeclared": int(frames_with_input),
            "framesWithAck": int(frames_with_ack),
            "ratio": coverage_ratio,
        },
        "totalMs": summarize_latency(total_values),
        "byKind": by_kind,
        "tts": tts_summary,
    }


def _normalize_frame_ack_kind(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"tts"}:
        return "tts"
    if raw in {"overlay", "ar"}:
        return "ar"
    if raw in {"haptic"}:
        return "haptic"
    return "other"


def extract_risk_latency_metrics_from_events_v1(
    events: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, int]] | None]:
    latencies: list[int] = []
    timing_values: dict[str, list[int]] = defaultdict(list)
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

        latency = _parse_int(event.get("latencyMs"))
        if latency is not None and latency >= 0:
            latencies.append(latency)

        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        debug = payload.get("debug")
        if not isinstance(debug, dict):
            continue
        timings = debug.get("timings")
        if not isinstance(timings, dict):
            continue
        for key in ("decodeMs", "depthMs", "featureMs", "ruleMs", "totalMs"):
            value = _parse_int(timings.get(key))
            if value is not None and value >= 0:
                timing_values[key].append(value)

    latency_stats = summarize_latency(latencies)
    timings_summary: dict[str, dict[str, int]] = {}
    for key, values in timing_values.items():
        stats = summarize_latency(values)
        timings_summary[key] = {
            "count": int(stats.get("count", 0) or 0),
            "p50": int(stats.get("p50", 0) or 0),
            "p90": int(stats.get("p90", 0) or 0),
            "max": int(stats.get("max", 0) or 0),
        }

    return latency_stats, timings_summary or None


def _merge_inference_fields(target: dict[str, Any], payload: dict[str, Any]) -> None:
    backend_value = payload.get("backend")
    model_value = payload.get("model")
    endpoint_value = payload.get("endpoint")
    backend = str(backend_value).strip().lower() if backend_value is not None else ""
    model = str(model_value).strip() if model_value is not None else ""
    endpoint = str(endpoint_value).strip() if endpoint_value is not None else ""
    if backend:
        target["backend"] = backend
    if model:
        target["model"] = model
    if endpoint:
        target["endpoint"] = endpoint


def _merge_seg_prompt_fields(target: dict[str, Any], payload: dict[str, Any]) -> None:
    target["promptPresent"] = True
    out_payload = payload.get("out")
    out_payload = out_payload if isinstance(out_payload, dict) else {}
    truncation_payload = payload.get("truncation")
    truncation_payload = truncation_payload if isinstance(truncation_payload, dict) else {}
    budget_payload = payload.get("budget")
    budget_payload = budget_payload if isinstance(budget_payload, dict) else {}
    complexity_payload = payload.get("complexity")
    complexity_payload = complexity_payload if isinstance(complexity_payload, dict) else {}

    in_targets = _to_nonnegative_int(payload.get("targetsCount"))
    in_text_chars = _to_nonnegative_int(payload.get("textChars"))
    in_boxes = _to_nonnegative_int(payload.get("boxesCount"))
    in_points = _to_nonnegative_int(payload.get("pointsCount"))

    out_targets = _to_nonnegative_int(out_payload.get("targetsCount", payload.get("targetsCount")))
    out_text_chars = _to_nonnegative_int(out_payload.get("textChars", payload.get("textChars")))
    out_boxes = _to_nonnegative_int(out_payload.get("boxesCount", payload.get("boxesCount")))
    out_points = _to_nonnegative_int(out_payload.get("pointsCount", payload.get("pointsCount")))
    out_chars_total = _to_nonnegative_int(out_payload.get("charsTotal"))

    target["promptTextCharsTotal"] = int(target.get("promptTextCharsTotal", 0) or 0) + out_text_chars
    target["promptBoxesTotal"] = int(target.get("promptBoxesTotal", 0) or 0) + out_boxes
    target["promptPointsTotal"] = int(target.get("promptPointsTotal", 0) or 0) + out_points
    target["promptTargetsTotal"] = int(target.get("promptTargetsTotal", 0) or 0) + out_targets

    target["promptTargetsInTotal"] = int(target.get("promptTargetsInTotal", 0) or 0) + in_targets
    target["promptTextInCharsTotal"] = int(target.get("promptTextInCharsTotal", 0) or 0) + in_text_chars
    target["promptBoxesInTotal"] = int(target.get("promptBoxesInTotal", 0) or 0) + in_boxes
    target["promptPointsInTotal"] = int(target.get("promptPointsInTotal", 0) or 0) + in_points

    target["promptTargetsOutTotal"] = int(target.get("promptTargetsOutTotal", 0) or 0) + out_targets
    target["promptTextOutCharsTotal"] = int(target.get("promptTextOutCharsTotal", 0) or 0) + out_text_chars
    target["promptBoxesOutTotal"] = int(target.get("promptBoxesOutTotal", 0) or 0) + out_boxes
    target["promptPointsOutTotal"] = int(target.get("promptPointsOutTotal", 0) or 0) + out_points
    target["promptCharsOutTotal"] = int(target.get("promptCharsOutTotal", 0) or 0) + out_chars_total

    target["promptTargetsDroppedTotal"] = int(target.get("promptTargetsDroppedTotal", 0) or 0) + _to_nonnegative_int(
        truncation_payload.get("targetsDropped")
    )
    target["promptBoxesDroppedTotal"] = int(target.get("promptBoxesDroppedTotal", 0) or 0) + _to_nonnegative_int(
        truncation_payload.get("boxesDropped")
    )
    target["promptPointsDroppedTotal"] = int(target.get("promptPointsDroppedTotal", 0) or 0) + _to_nonnegative_int(
        truncation_payload.get("pointsDropped")
    )
    target["promptTextCharsDroppedTotal"] = int(target.get("promptTextCharsDroppedTotal", 0) or 0) + _to_nonnegative_int(
        truncation_payload.get("textCharsDropped")
    )

    target["promptWarningsCountTotal"] = int(target.get("promptWarningsCountTotal", 0) or 0) + _to_nonnegative_int(
        payload.get("warningsCount")
    )
    packed = payload.get("packed")
    if isinstance(packed, bool):
        if packed:
            target["promptPackedTrueCount"] = int(target.get("promptPackedTrueCount", 0) or 0) + 1
        else:
            target["promptPackedFalseCount"] = int(target.get("promptPackedFalseCount", 0) or 0) + 1

    if _to_bool(complexity_payload.get("hasTargets")):
        target["promptComplexityHasTargetsCount"] = int(target.get("promptComplexityHasTargetsCount", 0) or 0) + 1
    if _to_bool(complexity_payload.get("hasText")):
        target["promptComplexityHasTextCount"] = int(target.get("promptComplexityHasTextCount", 0) or 0) + 1
    if _to_bool(complexity_payload.get("hasBoxes")):
        target["promptComplexityHasBoxesCount"] = int(target.get("promptComplexityHasBoxesCount", 0) or 0) + 1
    if _to_bool(complexity_payload.get("hasPoints")):
        target["promptComplexityHasPointsCount"] = int(target.get("promptComplexityHasPointsCount", 0) or 0) + 1
    target["promptComplexityScoreTotal"] = float(target.get("promptComplexityScoreTotal", 0.0) or 0.0) + _to_nonnegative_float(
        complexity_payload.get("score")
    )

    budget_max_chars = _to_nonnegative_int(budget_payload.get("maxChars"))
    if budget_max_chars > 0:
        target["promptBudgetMaxChars"] = budget_max_chars
    budget_max_targets = _to_nonnegative_int(budget_payload.get("maxTargets"))
    if budget_max_targets > 0:
        target["promptBudgetMaxTargets"] = budget_max_targets
    budget_max_boxes = _to_nonnegative_int(budget_payload.get("maxBoxes"))
    if budget_max_boxes > 0:
        target["promptBudgetMaxBoxes"] = budget_max_boxes
    budget_max_points = _to_nonnegative_int(budget_payload.get("maxPoints"))
    if budget_max_points > 0:
        target["promptBudgetMaxPoints"] = budget_max_points
    budget_mode = str(budget_payload.get("mode", "")).strip()
    if budget_mode:
        target["promptBudgetMode"] = budget_mode

    target["promptEventCount"] = int(target.get("promptEventCount", 0) or 0) + 1
    prompt_version = payload.get("promptVersion")
    version_text = "" if prompt_version is None else str(prompt_version).strip()
    if version_text:
        versions = target.get("_promptVersionCounts")
        if not isinstance(versions, Counter):
            versions = Counter()
        versions[version_text] += 1
        target["_promptVersionCounts"] = versions
        target["promptVersion"] = version_text


def _finalize_seg_prompt_bucket(target: dict[str, Any]) -> None:
    versions = target.pop("_promptVersionCounts", None)
    if isinstance(versions, Counter) and versions:
        most_common = versions.most_common(1)[0][0]
        target["promptVersion"] = most_common
        target["promptVersionDiversityCount"] = len(versions)
    elif bool(target.get("promptPresent")):
        if "promptVersion" not in target:
            target["promptVersion"] = None
        target["promptVersionDiversityCount"] = 0
    event_count = int(target.get("promptEventCount", 0) or 0)
    if event_count > 0:
        score_total = float(target.get("promptComplexityScoreTotal", 0.0) or 0.0)
        target["promptComplexityScoreMean"] = round(score_total / float(event_count), 6)
    elif "promptComplexityScoreMean" not in target:
        target["promptComplexityScoreMean"] = 0.0


def _to_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _to_nonnegative_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except Exception:
        return 0.0


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _has_any_inference(summary: dict[str, dict[str, Any]]) -> bool:
    for tool in ("ocr", "risk", "seg", "depth"):
        bucket = summary.get(tool, {})
        if not isinstance(bucket, dict):
            continue
        if tool == "seg" and bool(bucket.get("promptPresent")):
            return True
        if any(str(bucket.get(key, "")).strip() for key in ("backend", "model", "endpoint")):
            return True
    return False
