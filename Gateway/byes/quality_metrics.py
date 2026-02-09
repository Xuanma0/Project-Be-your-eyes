from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

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


def load_gt_risk_jsonl(path: Path) -> dict[int, list[dict[str, Any]]]:
    rows: dict[int, list[dict[str, Any]]] = {}
    for item in _iter_jsonl(path):
        if not isinstance(item, dict):
            continue
        seq = _extract_frame_seq(item)
        if seq is None:
            continue
        hazards = _extract_hazards(item)
        rows[seq] = hazards
    return rows


def extract_pred_ocr_from_ws_events(ws_events_jsonl_path: Path) -> dict[int, dict[str, Any]]:
    preds: dict[int, dict[str, Any]] = {}
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


def extract_pred_hazards_from_ws_events(ws_events_jsonl_path: Path) -> dict[int, list[dict[str, Any]]]:
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
        hazards = _extract_hazards(event)
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
            uniq.append({"hazardKind": kind})
        compact[seq] = uniq
    return compact


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
) -> dict[str, Any]:
    frames_total_safe = max(0, int(frames_total))
    frames_with_gt = len(gt_map)
    frames_with_pred = len(pred_map)
    coverage = (frames_with_pred / frames_total_safe) if frames_total_safe > 0 else 0.0

    exact_matches = 0
    char_distance = 0
    char_total = 0
    word_distance = 0
    word_total = 0
    latencies: list[int] = []

    for seq, gt_text in gt_map.items():
        pred_text = str(pred_map.get(seq, {}).get("text", ""))
        if _normalize_text(gt_text) == _normalize_text(pred_text):
            exact_matches += 1

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

    metrics: dict[str, Any] = {
        "framesTotal": frames_total_safe,
        "framesWithGt": frames_with_gt,
        "framesWithPred": frames_with_pred,
        "coverage": coverage,
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
) -> dict[str, Any]:
    window = max(0, int(window_frames))
    by_kind_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})

    pred_entries: list[dict[str, Any]] = []
    for seq, hazards in pred_map.items():
        for hazard in hazards:
            kind = _normalize_kind(hazard.get("hazardKind"))
            if not kind:
                continue
            pred_entries.append({"seq": int(seq), "kind": kind, "used": False})

    gt_critical_count = 0
    hit_critical_count = 0
    miss_critical_count = 0

    for gt_seq, hazards in gt_map.items():
        for hazard in hazards:
            kind = _normalize_kind(hazard.get("hazardKind"))
            if not kind:
                continue
            severity = str(hazard.get("severity", "")).strip().lower()
            is_critical = severity == "critical"
            if is_critical:
                gt_critical_count += 1

            best_idx = -1
            best_dist = 10**9
            for idx, pred in enumerate(pred_entries):
                if pred["used"]:
                    continue
                if pred["kind"] != kind:
                    continue
                dist = abs(int(pred["seq"]) - int(gt_seq))
                if dist > window:
                    continue
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx

            if best_idx >= 0:
                pred_entries[best_idx]["used"] = True
                by_kind_counts[kind]["tp"] += 1
                if is_critical:
                    hit_critical_count += 1
            else:
                by_kind_counts[kind]["fn"] += 1
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
    }


def compute_quality_score(
    safety_score: float,
    ocr_metrics: dict[str, Any] | None,
    risk_metrics: dict[str, Any] | None,
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

    payload = obj.get("payload")
    if isinstance(payload, dict):
        return _extract_latency_ms(payload)
    return None


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


def _extract_hazards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    hazards: list[dict[str, Any]] = []

    def push(item: dict[str, Any]) -> None:
        kind = _normalize_kind(item.get("hazardKind") or item.get("kind") or item.get("type"))
        if not kind:
            return
        severity_raw = item.get("severity")
        severity = str(severity_raw).strip().lower() if isinstance(severity_raw, str) else None
        hazards.append({"hazardKind": kind, "severity": severity})

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
            hazards.extend(_extract_hazards(nested))
    return hazards


def _normalize_kind(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


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
