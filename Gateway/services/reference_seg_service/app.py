from __future__ import annotations

import json
import os
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


def _default_fixture_path() -> Path:
    return _repo_root() / "Gateway" / "tests" / "fixtures" / "run_package_with_seg_gt_min" / "gt" / "seg_gt_v1.json"


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
    return {"label": label, "score": score, "bbox": bbox}


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


def _load_state() -> dict[str, Any]:
    fixture_path_text = str(os.getenv("BYES_REF_SEG_FIXTURE_PATH", "")).strip()
    fixture_path = Path(fixture_path_text) if fixture_path_text else _default_fixture_path()
    expected_run_id = str(os.getenv("BYES_REF_SEG_RUN_ID", "fixture-seg-gt")).strip() or "fixture-seg-gt"
    endpoint_override = str(os.getenv("BYES_REF_SEG_ENDPOINT", "")).strip() or None
    if not fixture_path.exists():
        raise RuntimeError(f"fixture_not_found:{fixture_path}")
    mapping, warnings_count = _load_fixture_mapping(fixture_path, expected_run_id)
    return {
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
                elif targets:
                    target_set = set(targets)
                    filtered = [item for item in segments if str(item.get("label", "")).strip().lower() in target_set]
                    segments = filtered
                    if not segments and warning is None:
                        warning = "no_segments_after_target_filter"
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
    if warnings_count > 0:
        response["warningsCount"] = warnings_count
    return response
