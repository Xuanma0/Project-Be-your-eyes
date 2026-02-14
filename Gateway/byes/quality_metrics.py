from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

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


def extract_inference_summary_from_ws_events(ws_events_jsonl_path: Path) -> dict[str, dict[str, str | None]]:
    summary: dict[str, dict[str, str | None]] = {
        "ocr": {"backend": None, "model": None, "endpoint": None},
        "risk": {"backend": None, "model": None, "endpoint": None},
        "seg": {"backend": None, "model": None, "endpoint": None},
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
        else:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        _merge_inference_fields(bucket, payload)

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
        if "seg" in blob or "segment" in blob:
            _merge_inference_fields(summary["seg"], event.get("payload") if isinstance(event.get("payload"), dict) else event)

    return summary


def infer_inference_summary_from_events_v1(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    summary: dict[str, dict[str, str | None]] = {
        "ocr": {"backend": None, "model": None, "endpoint": None},
        "risk": {"backend": None, "model": None, "endpoint": None},
        "seg": {"backend": None, "model": None, "endpoint": None},
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
        else:
            continue

        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        _merge_inference_fields(bucket, payload)
    return summary


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


def _merge_inference_fields(target: dict[str, str | None], payload: dict[str, Any]) -> None:
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


def _has_any_inference(summary: dict[str, dict[str, str | None]]) -> bool:
    for tool in ("ocr", "risk", "seg"):
        bucket = summary.get(tool, {})
        if not isinstance(bucket, dict):
            continue
        if any(str(bucket.get(key, "")).strip() for key in ("backend", "model", "endpoint")):
            return True
    return False
