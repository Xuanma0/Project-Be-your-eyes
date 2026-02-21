from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel


APP_TITLE = "BYES Reference OCR Service"
MODEL_ID = "reference-ocr-v1"
BACKEND = "reference"


class OcrRequest(BaseModel):
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
    return _repo_root() / "Gateway" / "tests" / "fixtures" / "run_package_with_ocr_gt_min"


def _fixture_path_from_dir(fixture_dir: Path) -> Path:
    return fixture_dir / "gt" / "ocr_gt_v1.json"


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


def _normalize_line(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        text = str(item).strip()
        return {"text": text} if text else None
    if not isinstance(item, dict):
        return None
    text = str(item.get("text", "")).strip()
    if not text:
        return None
    out: dict[str, Any] = {"text": text}
    score = _to_float(item.get("score"))
    if score is not None:
        out["score"] = max(0.0, min(1.0, score))
    bbox = _normalize_bbox(item.get("bbox"))
    if bbox is not None:
        out["bbox"] = bbox
    return out


def _normalize_frame_rows(frames: list[Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
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
        lines_raw = row.get("lines")
        if not isinstance(lines_raw, list):
            text_fallback = str(row.get("text", "")).strip()
            lines_raw = [{"text": text_fallback}] if text_fallback else []
        lines: list[dict[str, Any]] = []
        for item in lines_raw:
            normalized = _normalize_line(item)
            if normalized is not None:
                lines.append(normalized)
        payload: dict[str, Any] = {"lines": lines}
        image_width = row.get("imageWidth")
        image_height = row.get("imageHeight")
        try:
            if image_width is not None and int(image_width) > 0:
                payload["imageWidth"] = int(image_width)
        except Exception:
            pass
        try:
            if image_height is not None and int(image_height) > 0:
                payload["imageHeight"] = int(image_height)
        except Exception:
            pass
        out[frame_seq] = payload
    return out


def _load_fixture_mapping(path: Path, default_run_id: str) -> tuple[dict[str, dict[int, dict[str, Any]]], int]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    mapping: dict[str, dict[int, dict[str, Any]]] = {}
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
        frames_raw = payload.get("frames")
        if isinstance(frames_raw, list):
            run_id = str(payload.get("runId", "")).strip() or default_run_id
            mapping[run_id] = _normalize_frame_rows(frames_raw)
            return mapping, warnings_count

    raise ValueError("unsupported fixture payload format")


def _resolve_fixture_inputs() -> tuple[Path, Path]:
    fixture_dir_text = str(os.getenv("BYES_REF_OCR_FIXTURE_DIR", "")).strip()
    fixture_path_text = str(os.getenv("BYES_REF_OCR_FIXTURE_PATH", "")).strip()

    if fixture_dir_text:
        fixture_dir = Path(fixture_dir_text)
        return fixture_dir, _fixture_path_from_dir(fixture_dir)

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
    expected_run_id = str(os.getenv("BYES_REF_OCR_RUN_ID", "fixture-ocr-gt")).strip() or "fixture-ocr-gt"
    endpoint_override = str(os.getenv("BYES_REF_OCR_ENDPOINT", "")).strip() or None
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
    app.state.ocr_state = _load_state()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    state = getattr(app.state, "ocr_state", _load_state())
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


@app.post("/ocr")
def ocr_read(request: OcrRequest, raw_request: Request) -> dict[str, Any]:
    state = getattr(app.state, "ocr_state", _load_state())
    mapping = state.get("mapping", {})
    mapping = mapping if isinstance(mapping, dict) else {}

    run_id = str(request.runId or "").strip()
    warning: str | None = None
    warnings_count = int(state.get("warningsCount", 0) or 0)
    frame_payload: dict[str, Any] | None = None

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
                frame_payload = run_map.get(int(frame_seq))
                if not isinstance(frame_payload, dict):
                    warning = "frame_not_found"
                    warnings_count += 1

    endpoint = state.get("endpoint")
    endpoint_text = str(endpoint).strip() if endpoint is not None else ""
    if not endpoint_text:
        endpoint_text = str(raw_request.url).split("?", 1)[0]

    lines: list[dict[str, Any]] = []
    if isinstance(frame_payload, dict):
        lines_raw = frame_payload.get("lines")
        if isinstance(lines_raw, list):
            lines = [dict(item) for item in lines_raw if isinstance(item, dict)]

    response: dict[str, Any] = {
        "schemaVersion": "byes.ocr.v1",
        "runId": run_id or None,
        "frameSeq": request.frameSeq,
        "lines": lines,
        "linesCount": len(lines),
        "backend": BACKEND,
        "model": MODEL_ID,
        "endpoint": endpoint_text,
    }
    if isinstance(frame_payload, dict):
        image_width = frame_payload.get("imageWidth")
        image_height = frame_payload.get("imageHeight")
        if isinstance(image_width, int) and image_width > 0:
            response["imageWidth"] = image_width
        if isinstance(image_height, int) and image_height > 0:
            response["imageHeight"] = image_height
    if warning:
        response["warning"] = warning
    if warnings_count > 0:
        response["warningsCount"] = warnings_count
    return response
