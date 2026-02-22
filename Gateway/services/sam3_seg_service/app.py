from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel


APP_TITLE = "BYES SAM3 Segmentation Service"
BACKEND = "sam3"


class SegRequest(BaseModel):
    runId: str | None = None
    frameSeq: int | None = None
    image_b64: str | None = None
    targets: list[str] | None = None
    prompt: dict[str, Any] | None = None
    mode: str | None = None


app = FastAPI(title=APP_TITLE)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_fixture_dir() -> Path:
    return _repo_root() / "Gateway" / "tests" / "fixtures" / "run_package_with_seg_gt_min"


def _fixture_path_from_dir(fixture_dir: Path) -> Path:
    return fixture_dir / "gt" / "seg_gt_v1.json"


def _now_model_id() -> str:
    return str(os.getenv("BYES_SAM3_MODEL_ID", "sam3-v1")).strip() or "sam3-v1"


def _normalize_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower() or "fixture"
    if mode not in {"fixture", "sam3"}:
        return "fixture"
    return mode


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _normalize_bbox(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    parsed: list[float] = []
    for item in raw:
        value = _to_float(item)
        if value is None:
            return None
        parsed.append(value)
    x0, y0, x1, y1 = parsed
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    if x1 <= x0:
        x1 = x0 + 1.0
    if y1 <= y0:
        y1 = y0 + 1.0
    return [x0, y0, x1, y1]


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


def _normalize_segment(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label", "")).strip()
    if not label:
        return None
    bbox = _normalize_bbox(raw.get("bbox"))
    if bbox is None:
        return None
    score_raw = _to_float(raw.get("score"))
    score = 1.0 if score_raw is None else max(0.0, min(1.0, score_raw))
    out: dict[str, Any] = {"label": label, "score": score, "bbox": bbox}
    mask = _normalize_mask(raw.get("mask"))
    if isinstance(mask, dict):
        out["mask"] = mask
    return out


def _normalize_targets(raw: list[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        value = str(item or "").strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _prompt_targets(prompt: dict[str, Any] | None) -> list[str]:
    if not isinstance(prompt, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    targets = prompt.get("targets")
    if isinstance(targets, list):
        for item in targets:
            value = str(item or "").strip().lower()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
    text = str(prompt.get("text", "")).strip().lower()
    if text:
        for token in text.replace(",", " ").replace("/", " ").split():
            token = token.strip().lower()
            if len(token) < 2 or token in seen:
                continue
            seen.add(token)
            out.append(token)
    return out


def _normalize_frame_rows(rows: list[Any]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            seq = int(row.get("frameSeq", row.get("seq")))
        except Exception:
            continue
        if seq <= 0:
            continue
        objects = row.get("objects", row.get("segments"))
        if not isinstance(objects, list):
            continue
        segments: list[dict[str, Any]] = []
        for item in objects:
            normalized = _normalize_segment(item)
            if normalized is not None:
                segments.append(normalized)
        out[int(seq)] = segments
    return out


def _load_fixture_mapping(path: Path, default_run_id: str) -> tuple[dict[str, dict[int, list[dict[str, Any]]]], int]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    mapping: dict[str, dict[int, list[dict[str, Any]]]] = {}
    warnings_count = 0

    if isinstance(payload, dict) and isinstance(payload.get("runs"), dict):
        for run_id, rows in payload["runs"].items():
            run_id_text = str(run_id or "").strip()
            if not run_id_text or not isinstance(rows, list):
                warnings_count += 1
                continue
            mapping[run_id_text] = _normalize_frame_rows(rows)
        return mapping, warnings_count

    if isinstance(payload, dict):
        frames = payload.get("frames")
        if isinstance(frames, list):
            run_id = str(payload.get("runId", "")).strip() or default_run_id
            mapping[run_id] = _normalize_frame_rows(frames)
            return mapping, warnings_count

    raise ValueError("unsupported fixture payload format")


def _resolve_fixture_inputs() -> tuple[Path, Path]:
    fixture_dir_text = str(os.getenv("BYES_SAM3_FIXTURE_DIR", "")).strip()
    fixture_path_text = str(os.getenv("BYES_SAM3_FIXTURE_PATH", "")).strip()
    if fixture_dir_text:
        fixture_dir = Path(fixture_dir_text)
        return fixture_dir, _fixture_path_from_dir(fixture_dir)
    if fixture_path_text:
        fixture_path = Path(fixture_path_text)
        fixture_dir = fixture_path.parent.parent if fixture_path.parent.name.lower() == "gt" else fixture_path.parent
        return fixture_dir, fixture_path
    fixture_dir = _default_fixture_dir()
    return fixture_dir, _fixture_path_from_dir(fixture_dir)


def _load_state() -> dict[str, Any]:
    mode = _normalize_mode(os.getenv("BYES_SAM3_MODE", "fixture"))
    expected_run_id = str(os.getenv("BYES_SAM3_RUN_ID", "fixture-seg-gt")).strip() or "fixture-seg-gt"
    endpoint_override = str(os.getenv("BYES_SAM3_ENDPOINT", "")).strip() or None
    timeout_ms = max(1, int(str(os.getenv("BYES_SAM3_TIMEOUT_MS", "2000")).strip() or "2000"))
    model_id = _now_model_id()
    ckpt_path = str(os.getenv("BYES_SAM3_CKPT_PATH", "")).strip() or None
    device = str(os.getenv("BYES_SAM3_DEVICE", "cpu")).strip() or "cpu"

    state: dict[str, Any] = {
        "mode": mode,
        "modelId": model_id,
        "endpoint": endpoint_override,
        "timeoutMs": timeout_ms,
        "device": device,
        "ckptPath": ckpt_path,
        "sam3Ready": False,
        "sam3LoadError": None,
        "fixtureDir": None,
        "fixturePath": None,
        "expectedRunId": expected_run_id,
        "mapping": {},
        "warningsCount": 0,
    }

    if mode == "fixture":
        fixture_dir, fixture_path = _resolve_fixture_inputs()
        if not fixture_path.exists():
            raise RuntimeError(f"fixture_not_found:{fixture_path}")
        mapping, warnings_count = _load_fixture_mapping(fixture_path, expected_run_id)
        state["fixtureDir"] = str(fixture_dir)
        state["fixturePath"] = str(fixture_path)
        state["mapping"] = mapping
        state["warningsCount"] = int(warnings_count)
        state["sam3Ready"] = True
        return state

    # sam3 mode: keep service alive even when checkpoint is missing to provide clear health diagnostics.
    if not ckpt_path:
        state["sam3LoadError"] = "missing_BYES_SAM3_CKPT_PATH"
        return state
    ckpt_file = Path(ckpt_path)
    if not ckpt_file.exists():
        state["sam3LoadError"] = f"checkpoint_not_found:{ckpt_file}"
        return state
    state["sam3Ready"] = True
    return state


@app.on_event("startup")
def _startup() -> None:
    app.state.sam3_state = _load_state()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    state = getattr(app.state, "sam3_state", _load_state())
    mapping = state.get("mapping")
    mapping = mapping if isinstance(mapping, dict) else {}
    return {
        "ok": True,
        "backend": BACKEND,
        "model": state.get("modelId"),
        "mode": state.get("mode"),
        "sam3Ready": bool(state.get("sam3Ready")),
        "sam3LoadError": state.get("sam3LoadError"),
        "device": state.get("device"),
        "ckptPath": state.get("ckptPath"),
        "fixtureDir": state.get("fixtureDir"),
        "fixturePath": state.get("fixturePath"),
        "runIds": sorted(str(k) for k in mapping.keys()),
        "warningsCount": int(state.get("warningsCount", 0) or 0),
    }


@app.post("/seg")
def segment(request: SegRequest, raw_request: Request) -> dict[str, Any]:
    state = getattr(app.state, "sam3_state", _load_state())
    mode = _normalize_mode(request.mode or state.get("mode"))
    warnings_count = int(state.get("warningsCount", 0) or 0)
    warning: str | None = None
    segments: list[dict[str, Any]] = []

    targets = _normalize_targets(request.targets)
    prompt_targets = _prompt_targets(request.prompt)
    label_filter = sorted(set(targets + prompt_targets))

    if mode == "sam3":
        load_error = str(state.get("sam3LoadError") or "").strip()
        if load_error:
            raise HTTPException(status_code=500, detail=f"sam3_not_ready:{load_error}")
        # Stub behavior in v4.65: keep contract shape and health observability without heavy runtime deps.
        warning = "sam3_mode_stub_no_inference"
        warnings_count += 1
    else:
        mapping = state.get("mapping")
        mapping = mapping if isinstance(mapping, dict) else {}
        run_id = str(request.runId or "").strip()
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

    if segments and label_filter:
        label_set = set(label_filter)
        filtered = [row for row in segments if str(row.get("label", "")).strip().lower() in label_set]
        segments = filtered

    endpoint = str(state.get("endpoint") or "").strip()
    if not endpoint:
        endpoint = str(raw_request.url).split("?", 1)[0]

    response: dict[str, Any] = {
        "segments": segments,
        "segmentsCount": len(segments),
        "backend": BACKEND,
        "model": str(state.get("modelId") or _now_model_id()),
        "endpoint": endpoint,
    }
    if targets:
        response["targetsCount"] = len(targets)
        response["targetsUsed"] = targets
    if warning:
        response["warning"] = warning
    if warnings_count > 0:
        response["warningsCount"] = int(warnings_count)
    return response
