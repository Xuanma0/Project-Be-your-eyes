from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel


APP_TITLE = "BYES Reference Segmentation Service"
MODEL_ID = "reference-seg-v1"
BACKEND = "reference"


class SegRequest(BaseModel):
    image_b64: str | None = None
    frameSeq: int | None = None
    runId: str | None = None
    tsMs: int | None = None
    targets: list[str] | None = None
    prompt: dict[str, Any] | None = None


app = FastAPI(title=APP_TITLE)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_fixture_dir() -> Path:
    return _repo_root() / "Gateway" / "tests" / "fixtures" / "run_package_with_seg_gt_min"


def _fixture_path_from_dir(fixture_dir: Path) -> Path:
    return fixture_dir / "gt" / "seg_gt_v1.json"


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _normalize_bbox(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    coords: list[float] = []
    for value in raw:
        parsed = _to_float(value)
        if parsed is None:
            return None
        coords.append(parsed)
    x0, y0, x1, y1 = coords
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    if x1 <= x0:
        x1 = x0 + 1.0
    if y1 <= y0:
        y1 = y0 + 1.0
    return [x0, y0, x1, y1]


def _normalize_segment(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    label = str(item.get("label", "")).strip()
    if not label:
        return None
    bbox = _normalize_bbox(item.get("bbox"))
    if bbox is None:
        return None
    score_raw = _to_float(item.get("score"))
    score = 1.0 if score_raw is None else max(0.0, min(1.0, float(score_raw)))
    out: dict[str, Any] = {"label": label, "score": score, "bbox": bbox}
    mask = _normalize_mask(item.get("mask"))
    if isinstance(mask, dict):
        out["mask"] = mask
    return out


def _normalize_mask(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if str(raw.get("format", "")).strip() != "rle_v1":
        return None
    size_raw = raw.get("size")
    if not isinstance(size_raw, list) or len(size_raw) != 2:
        return None
    try:
        h = int(size_raw[0])
        w = int(size_raw[1])
    except Exception:
        return None
    if h <= 0 or w <= 0:
        return None
    counts_raw = raw.get("counts")
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


def _normalize_targets(raw_targets: list[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_targets or []:
        text = str(item or "").strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_prompt(prompt: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(prompt, dict):
        return {}
    out: dict[str, Any] = {}
    targets = _normalize_targets(prompt.get("targets"))
    if targets:
        out["targets"] = targets

    text = str(prompt.get("text", "")).strip()
    if text:
        out["text"] = text

    boxes_raw = prompt.get("boxes")
    if isinstance(boxes_raw, list):
        boxes: list[list[float]] = []
        for item in boxes_raw:
            normalized = _normalize_bbox(item)
            if normalized is not None:
                boxes.append(normalized)
        if boxes:
            out["boxes"] = boxes

    points_raw = prompt.get("points")
    if isinstance(points_raw, list):
        points: list[dict[str, float]] = []
        for item in points_raw:
            if not isinstance(item, dict):
                continue
            x = _to_float(item.get("x"))
            y = _to_float(item.get("y"))
            if x is None or y is None:
                continue
            points.append({"x": float(x), "y": float(y)})
        if points:
            out["points"] = points

    meta_raw = prompt.get("meta")
    if isinstance(meta_raw, dict):
        prompt_version = str(meta_raw.get("promptVersion", "")).strip()
        if prompt_version:
            out["meta"] = {"promptVersion": prompt_version}

    return out


def _extract_labels_from_prompt_text(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\s,;/|]+", text):
        normalized = str(token or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(normalized)
    return tokens


def _bbox_overlap_area(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    width = ix1 - ix0
    height = iy1 - iy0
    if width <= 0 or height <= 0:
        return 0.0
    return float(width * height)


def _point_in_bbox(point: dict[str, float], bbox: list[float]) -> bool:
    x = float(point.get("x", 0.0))
    y = float(point.get("y", 0.0))
    x0, y0, x1, y1 = bbox
    return x0 <= x <= x1 and y0 <= y <= y1


def _filter_segments_by_prompt(
    segments: list[dict[str, Any]],
    *,
    targets: list[str],
    prompt: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    if not segments:
        return segments, None

    original = [dict(item) for item in segments if isinstance(item, dict)]
    candidate = [dict(item) for item in original]
    prompt_targets = _normalize_targets(prompt.get("targets"))
    prompt_text = str(prompt.get("text", "")).strip()
    text_targets = _extract_labels_from_prompt_text(prompt_text) if prompt_text else []
    label_filters = sorted(set(targets + prompt_targets + text_targets))

    if label_filters:
        label_set = set(label_filters)
        filtered = [item for item in candidate if str(item.get("label", "")).strip().lower() in label_set]
        if not filtered:
            return original, "prompt_filter_empty_fallback_targets_or_text"
        candidate = filtered

    boxes = prompt.get("boxes")
    if isinstance(boxes, list) and boxes:
        prompt_boxes: list[list[float]] = []
        for box in boxes:
            if isinstance(box, list) and len(box) == 4:
                normalized_box = _normalize_bbox(box)
                if normalized_box is not None:
                    prompt_boxes.append(normalized_box)
        if not prompt_boxes:
            boxes = []
    if isinstance(boxes, list) and boxes:
        filtered = []
        for item in candidate:
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            bbox_norm = _normalize_bbox(bbox)
            if bbox_norm is None:
                continue
            overlap = any(_bbox_overlap_area(bbox_norm, box) > 0.0 for box in prompt_boxes)
            if overlap:
                filtered.append(item)
        if not filtered:
            return original, "prompt_filter_empty_fallback_boxes"
        candidate = filtered

    points = prompt.get("points")
    if isinstance(points, list) and points:
        filtered = []
        for item in candidate:
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            bbox_norm = _normalize_bbox(bbox)
            if bbox_norm is None:
                continue
            if any(_point_in_bbox(point, bbox_norm) for point in points if isinstance(point, dict)):
                filtered.append(item)
        if not filtered:
            return original, "prompt_filter_empty_fallback_points"
        candidate = filtered

    return candidate, None


def _normalize_frame_rows(frames: list[Any]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for row in frames:
        if not isinstance(row, dict):
            continue
        frame_seq_raw = row.get("frameSeq", row.get("seq"))
        try:
            frame_seq = int(frame_seq_raw)
        except Exception:
            continue
        if frame_seq <= 0:
            continue
        objects = row.get("objects", row.get("segments"))
        if not isinstance(objects, list):
            continue
        segments: list[dict[str, Any]] = []
        for item in objects:
            normalized = _normalize_segment(item)
            if normalized is not None:
                segments.append(normalized)
        out[frame_seq] = segments
    return out


def _load_fixture_mapping(path: Path, default_run_id: str) -> tuple[dict[str, dict[int, list[dict[str, Any]]]], int]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    mapping: dict[str, dict[int, list[dict[str, Any]]]] = {}
    warnings_count = 0

    if isinstance(payload, dict) and isinstance(payload.get("runs"), dict):
        for run_id, frames_raw in payload.get("runs", {}).items():
            run_id_text = str(run_id or "").strip()
            if not run_id_text or not isinstance(frames_raw, list):
                warnings_count += 1
                continue
            mapping[run_id_text] = _normalize_frame_rows(frames_raw)
        return mapping, warnings_count

    if isinstance(payload, dict):
        frame_rows = payload.get("frames")
        if isinstance(frame_rows, list):
            run_id = str(payload.get("runId", "")).strip() or default_run_id
            mapping[run_id] = _normalize_frame_rows(frame_rows)
            return mapping, warnings_count

    raise ValueError("unsupported fixture payload format")


def _resolve_fixture_inputs() -> tuple[Path, Path]:
    fixture_dir_text = str(os.getenv("BYES_REF_SEG_FIXTURE_DIR", "")).strip()
    fixture_path_text = str(os.getenv("BYES_REF_SEG_FIXTURE_PATH", "")).strip()

    if fixture_dir_text:
        fixture_dir = Path(fixture_dir_text)
        fixture_path = _fixture_path_from_dir(fixture_dir)
        return fixture_dir, fixture_path

    if fixture_path_text:
        fixture_path = Path(fixture_path_text)
        if fixture_path.parent.name.lower() == "gt":
            fixture_dir = fixture_path.parent.parent
        else:
            fixture_dir = fixture_path.parent
        return fixture_dir, fixture_path

    fixture_dir = _default_fixture_dir()
    return fixture_dir, _fixture_path_from_dir(fixture_dir)


def _load_state() -> dict[str, Any]:
    fixture_dir, fixture_path = _resolve_fixture_inputs()
    expected_run_id = str(os.getenv("BYES_REF_SEG_RUN_ID", "fixture-seg-gt")).strip() or "fixture-seg-gt"
    endpoint_override = str(os.getenv("BYES_REF_SEG_ENDPOINT", "")).strip() or None
    if not fixture_path.exists():
        raise RuntimeError(f"fixture_not_found:{fixture_path}")
    mapping, warnings_count = _load_fixture_mapping(fixture_path, expected_run_id)
    return {
        "fixtureDir": str(fixture_dir),
        "fixturePath": str(fixture_path),
        "expectedRunId": expected_run_id,
        "endpoint": endpoint_override,
        "mapping": mapping,
        "warningsCount": warnings_count,
    }


@app.on_event("startup")
def _startup() -> None:
    app.state.seg_state = _load_state()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    state = getattr(app.state, "seg_state", _load_state())
    mapping = state.get("mapping", {})
    run_ids = sorted(str(key) for key in mapping.keys())
    return {
        "ok": True,
        "backend": BACKEND,
        "model": MODEL_ID,
        "fixtureDir": state.get("fixtureDir"),
        "fixturePath": state.get("fixturePath"),
        "expectedRunId": state.get("expectedRunId"),
        "runIds": run_ids,
        "warningsCount": int(state.get("warningsCount", 0) or 0),
    }


@app.post("/seg")
def segment(request: SegRequest, raw_request: Request) -> dict[str, Any]:
    state = getattr(app.state, "seg_state", _load_state())
    mapping = state.get("mapping", {})
    mapping = mapping if isinstance(mapping, dict) else {}

    run_id = str(request.runId or "").strip()
    warning: str | None = None
    warnings_count = int(state.get("warningsCount", 0) or 0)
    segments: list[dict[str, Any]] = []
    targets = _normalize_targets(request.targets)
    prompt = _normalize_prompt(request.prompt)
    prompt_warning: str | None = None

    if not run_id:
        warning = "missing_run_id"
        warnings_count += 1
    else:
        run_map = mapping.get(run_id)
        run_map = run_map if isinstance(run_map, dict) else None
        if run_map is None:
            warning = "run_id_not_found"
            warnings_count += 1
        else:
            frame_seq = request.frameSeq
            if frame_seq is None:
                warning = "missing_frame_seq"
                warnings_count += 1
            else:
                segments = [dict(item) for item in run_map.get(int(frame_seq), []) if isinstance(item, dict)]
                if not segments:
                    warning = "frame_not_found"
                    warnings_count += 1
                else:
                    filtered, prompt_warning = _filter_segments_by_prompt(segments, targets=targets, prompt=prompt)
                    segments = filtered
                    if prompt_warning:
                        warnings_count += 1

    endpoint = state.get("endpoint")
    endpoint_text = str(endpoint).strip() if endpoint is not None else ""
    if not endpoint_text:
        endpoint_text = str(raw_request.url).split("?", 1)[0]

    response = {
        "segments": segments,
        "segmentsCount": len(segments),
        "backend": BACKEND,
        "model": MODEL_ID,
        "endpoint": endpoint_text,
        "targetsCount": len(targets),
        "targetsUsed": targets,
    }
    if warning:
        response["warning"] = warning
    if prompt_warning:
        response["promptWarning"] = prompt_warning
    if warnings_count > 0:
        response["warningsCount"] = warnings_count
    return response
