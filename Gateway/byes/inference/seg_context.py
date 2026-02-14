from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Iterable


DEFAULT_SEG_CONTEXT_BUDGET = {
    "maxChars": 512,
    "maxSegments": 16,
    "mode": "topk_by_score",
}

_ALLOWED_MODES = {"topk_by_score", "label_grouped"}


def build_seg_context_from_events(
    events_v1_lines: Iterable[dict[str, Any]] | None,
    budget: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_budget = _normalize_budget(budget)
    mode = str(normalized_budget["mode"])
    max_chars = int(normalized_budget["maxChars"])
    max_segments = int(normalized_budget["maxSegments"])

    events = _normalize_events(events_v1_lines)
    run_id = _pick_run_id(events)

    seg_by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
    frame_order: list[int] = []
    prompt_targets_total = 0
    prompt_text_chars_total = 0
    prompt_versions: Counter[str] = Counter()

    for event in events:
        if str(event.get("category", "")).strip().lower() != "tool":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        name = str(event.get("name", "")).strip().lower()
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if name == "seg.prompt":
            prompt_targets_total += _to_nonnegative_int(payload.get("targetsCount"))
            prompt_text_chars_total += _to_nonnegative_int(payload.get("textChars"))
            prompt_version = str(payload.get("promptVersion", "")).strip()
            if prompt_version:
                prompt_versions[prompt_version] += 1
            continue
        if name != "seg.segment":
            continue
        frame_seq = _to_nonnegative_int(event.get("frameSeq"))
        if frame_seq not in frame_order:
            frame_order.append(frame_seq)
        segments = payload.get("segments")
        if not isinstance(segments, list):
            continue
        for row in segments:
            normalized = _normalize_segment(row)
            if normalized is not None:
                seg_by_frame[frame_seq].append(normalized)

    selected_source = _select_source_segments(seg_by_frame, frame_order)
    in_segments = len(selected_source)
    in_unique_labels = len({str(row.get("label", "")).strip().lower() for row in selected_source if str(row.get("label", "")).strip()})

    if mode == "label_grouped":
        selected_rows, summary_lines, segments_dropped, labels_dropped = _build_label_grouped(selected_source, max_segments)
    else:
        selected_rows, summary_lines, segments_dropped, labels_dropped = _build_topk(selected_source, max_segments)

    out_segments = len(selected_rows)
    out_unique_labels = len({str(row.get("label", "")).strip().lower() for row in selected_rows if str(row.get("label", "")).strip()})

    prompt_fragment = _render_prompt_fragment(summary_lines)
    if prompt_targets_total > 0 or prompt_text_chars_total > 0:
        prompt_fragment = (
            f"{prompt_fragment}\n[SEG_PROMPT] targets={prompt_targets_total} textChars={prompt_text_chars_total}"
            if prompt_fragment
            else f"[SEG_PROMPT] targets={prompt_targets_total} textChars={prompt_text_chars_total}"
        )

    in_chars_total = len(prompt_fragment)
    if len(prompt_fragment) > max_chars:
        prompt_fragment = prompt_fragment[:max_chars]
    out_chars_total = len(prompt_fragment)
    chars_dropped = max(0, in_chars_total - out_chars_total)
    token_approx = _token_approx(out_chars_total)

    prompt_version = prompt_versions.most_common(1)[0][0] if prompt_versions else ""
    summary_text = (
        f"mode={mode}; segments={out_segments}/{in_segments}; labels={out_unique_labels}/{in_unique_labels}; "
        f"promptVersion={prompt_version or 'n/a'}"
    )

    return {
        "schemaVersion": "seg.context.v1",
        "runId": run_id,
        "stats": {
            "in": {
                "segments": int(in_segments),
                "uniqueLabels": int(in_unique_labels),
                "charsTotal": int(in_chars_total),
            },
            "out": {
                "segments": int(out_segments),
                "uniqueLabels": int(out_unique_labels),
                "charsTotal": int(out_chars_total),
                "tokenApprox": int(token_approx),
            },
            "truncation": {
                "segmentsDropped": int(max(0, segments_dropped)),
                "labelsDropped": int(max(0, labels_dropped)),
                "charsDropped": int(max(0, chars_dropped)),
            },
        },
        "budget": {
            "maxChars": int(max_chars),
            "maxSegments": int(max_segments),
            "mode": mode,
        },
        "text": {
            "summary": summary_text,
            "promptFragment": prompt_fragment,
        },
    }


def _normalize_events(events_v1_lines: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in events_v1_lines or []:
        if not isinstance(item, dict):
            continue
        event = item.get("event") if isinstance(item.get("event"), dict) else item
        if isinstance(event, dict):
            rows.append(event)
    return rows


def _pick_run_id(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        run_id = str(event.get("runId", "")).strip()
        if run_id:
            return run_id
    return "seg-context"


def _normalize_budget(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    mode = str(src.get("mode", DEFAULT_SEG_CONTEXT_BUDGET["mode"])).strip().lower()
    if mode not in _ALLOWED_MODES:
        mode = str(DEFAULT_SEG_CONTEXT_BUDGET["mode"])
    return {
        "maxChars": _to_nonnegative_int(src.get("maxChars"), int(DEFAULT_SEG_CONTEXT_BUDGET["maxChars"])),
        "maxSegments": _to_nonnegative_int(src.get("maxSegments"), int(DEFAULT_SEG_CONTEXT_BUDGET["maxSegments"])),
        "mode": mode,
    }


def _normalize_segment(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label", "")).strip()
    if not label:
        return None
    bbox = raw.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    coords: list[float] = []
    for value in bbox:
        parsed = _to_float(value)
        if parsed is None:
            return None
        coords.append(parsed)
    score = _to_float(raw.get("score"))
    if score is None:
        score = 0.0
    score = max(0.0, min(1.0, float(score)))
    return {
        "label": label,
        "score": score,
        "bbox": coords,
    }


def _select_source_segments(seg_by_frame: dict[int, list[dict[str, Any]]], frame_order: list[int]) -> list[dict[str, Any]]:
    if not seg_by_frame:
        return []
    for frame_seq in sorted(frame_order, reverse=True):
        rows = seg_by_frame.get(frame_seq, [])
        if rows:
            return [dict(row) for row in rows if isinstance(row, dict)]
    all_rows: list[dict[str, Any]] = []
    for frame_seq in sorted(seg_by_frame.keys()):
        all_rows.extend([dict(row) for row in seg_by_frame.get(frame_seq, []) if isinstance(row, dict)])
    return all_rows


def _build_topk(
    source: list[dict[str, Any]],
    max_segments: int,
) -> tuple[list[dict[str, Any]], list[str], int, int]:
    if not source:
        return [], [], 0, 0
    ordered = sorted(
        source,
        key=lambda row: (
            -float(row.get("score", 0.0) or 0.0),
            str(row.get("label", "")).strip().lower(),
            tuple(float(v) for v in row.get("bbox", [])),
        ),
    )
    selected = ordered[:max(0, max_segments)]
    summary_lines = [_format_segment_line(row) for row in selected]
    in_labels = {str(row.get("label", "")).strip().lower() for row in source if str(row.get("label", "")).strip()}
    out_labels = {str(row.get("label", "")).strip().lower() for row in selected if str(row.get("label", "")).strip()}
    segments_dropped = max(0, len(source) - len(selected))
    labels_dropped = max(0, len(in_labels) - len(out_labels))
    return selected, summary_lines, segments_dropped, labels_dropped


def _build_label_grouped(
    source: list[dict[str, Any]],
    max_segments: int,
) -> tuple[list[dict[str, Any]], list[str], int, int]:
    if not source:
        return [], [], 0, 0
    grouped: dict[str, dict[str, Any]] = {}
    for row in source:
        label = str(row.get("label", "")).strip()
        if not label:
            continue
        key = label.lower()
        score = float(row.get("score", 0.0) or 0.0)
        item = grouped.get(key)
        if item is None:
            grouped[key] = {"label": label, "count": 1, "maxScore": score, "bbox": list(row.get("bbox", []))}
            continue
        item["count"] = int(item.get("count", 0) or 0) + 1
        if score > float(item.get("maxScore", 0.0) or 0.0):
            item["maxScore"] = score
            item["bbox"] = list(row.get("bbox", []))
    ordered = sorted(
        grouped.values(),
        key=lambda row: (
            -float(row.get("maxScore", 0.0) or 0.0),
            str(row.get("label", "")).strip().lower(),
        ),
    )
    selected_groups = ordered[:max(0, max_segments)]
    selected: list[dict[str, Any]] = []
    summary_lines: list[str] = []
    kept_segments = 0
    for row in selected_groups:
        count = int(row.get("count", 0) or 0)
        score = float(row.get("maxScore", 0.0) or 0.0)
        bbox = row.get("bbox", [])
        selected.append({"label": str(row.get("label", "")), "score": score, "bbox": list(bbox)})
        kept_segments += count
        summary_lines.append(
            f"{str(row.get('label', '')).strip()}x{count}({score:.2f}) bbox={_format_bbox(bbox)}"
        )
    segments_dropped = max(0, len(source) - kept_segments)
    labels_dropped = max(0, len(grouped) - len(selected_groups))
    return selected, summary_lines, segments_dropped, labels_dropped


def _render_prompt_fragment(lines: list[str]) -> str:
    if not lines:
        return "[SEG] no objects detected"
    return "[SEG] top objects: " + "; ".join(lines)


def _format_segment_line(row: dict[str, Any]) -> str:
    label = str(row.get("label", "")).strip() or "unknown"
    score = float(row.get("score", 0.0) or 0.0)
    return f"{label}({score:.2f}) bbox={_format_bbox(row.get('bbox', []))}"


def _format_bbox(raw: Any) -> str:
    if not isinstance(raw, list) or len(raw) != 4:
        return "[]"
    out: list[str] = []
    for value in raw:
        parsed = _to_float(value)
        if parsed is None:
            return "[]"
        if abs(parsed - round(parsed)) < 1e-6:
            out.append(str(int(round(parsed))))
        else:
            out.append(f"{parsed:.2f}")
    return "[" + ",".join(out) + "]"


def _token_approx(chars_total: int) -> int:
    if int(chars_total) <= 0:
        return 0
    return int(math.ceil(float(chars_total) / 4.0))


def _to_nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return int(default)
        return max(0, int(float(value)))
    except Exception:
        return int(default)


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None
