from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel


APP_TITLE = "BYES Reference SLAM Service"
MODEL_ID = "reference-slam-v1"
BACKEND = "reference"
_TRACKING_STATES = {"tracking", "lost", "relocalized", "initializing"}


class SlamRequest(BaseModel):
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
    return _repo_root() / "Gateway" / "tests" / "fixtures" / "run_package_with_slam_pose_gt_min"


def _fixture_path_from_dir(fixture_dir: Path) -> Path:
    return fixture_dir / "gt" / "slam_pose_gt_v1.json"


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _normalize_tracking_state(raw: Any) -> str:
    state = str(raw or "").strip().lower()
    if state in _TRACKING_STATES:
        return state
    return "unknown"


def _normalize_pose(raw: Any) -> tuple[dict[str, Any] | None, int]:
    warnings_count = 0
    if not isinstance(raw, dict):
        return None, 1

    t_raw = raw.get("t")
    q_raw = raw.get("q")
    if not isinstance(t_raw, list) or len(t_raw) != 3:
        return None, 1
    if not isinstance(q_raw, list) or len(q_raw) != 4:
        return None, 1

    t: list[float] = []
    for value in t_raw:
        parsed = _to_float(value)
        if parsed is None:
            return None, 1
        t.append(parsed)

    q: list[float] = []
    for value in q_raw:
        parsed = _to_float(value)
        if parsed is None:
            return None, 1
        q.append(parsed)

    norm = math.sqrt(sum(item * item for item in q))
    if norm > 1e-9:
        if abs(norm - 1.0) > 1e-3:
            warnings_count += 1
        q = [item / norm for item in q]
    else:
        warnings_count += 1
        q = [0.0, 0.0, 0.0, 1.0]

    pose: dict[str, Any] = {"t": t, "q": q}
    frame = str(raw.get("frame", "")).strip().lower()
    if frame in {"world_to_cam", "cam_to_world"}:
        pose["frame"] = frame
    map_id = raw.get("mapId")
    map_id_text = str(map_id).strip() if map_id is not None else ""
    if map_id_text:
        pose["mapId"] = map_id_text
    cov = raw.get("cov")
    if isinstance(cov, dict):
        pose["cov"] = cov
    return pose, warnings_count


def _normalize_frame_rows(frames: list[Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in frames:
        if not isinstance(row, dict):
            continue
        seq_raw = row.get("frameSeq", row.get("seq"))
        try:
            seq = int(seq_raw)
        except Exception:
            continue
        if seq <= 0:
            continue

        state = _normalize_tracking_state(row.get("trackingState"))
        pose, pose_warn = _normalize_pose(row.get("pose"))
        if pose is None:
            continue
        warnings_count = int(max(0, int(row.get("warningsCount", 0) or 0))) + int(pose_warn)
        payload: dict[str, Any] = {
            "trackingState": state,
            "pose": pose,
        }
        map_id = row.get("mapId")
        map_id_text = str(map_id).strip() if map_id is not None else ""
        if map_id_text:
            payload["mapId"] = map_id_text
        cov = row.get("cov")
        if isinstance(cov, dict):
            payload["cov"] = cov
        if warnings_count > 0:
            payload["warningsCount"] = warnings_count
        out[seq] = payload
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
    fixture_dir_text = str(os.getenv("BYES_REF_SLAM_FIXTURE_DIR", "")).strip()
    fixture_path_text = str(os.getenv("BYES_REF_SLAM_FIXTURE_PATH", "")).strip()

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
    expected_run_id = str(os.getenv("BYES_REF_SLAM_RUN_ID", "fixture-slam-gt")).strip() or "fixture-slam-gt"
    endpoint_override = str(os.getenv("BYES_REF_SLAM_ENDPOINT", "")).strip() or None
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
    app.state.slam_state = _load_state()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    state = getattr(app.state, "slam_state", _load_state())
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


@app.post("/slam/pose")
def slam_pose(request: SlamRequest, raw_request: Request) -> dict[str, Any]:
    state = getattr(app.state, "slam_state", _load_state())
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

    tracking_state = "lost"
    pose: dict[str, Any] = {
        "t": [0.0, 0.0, 0.0],
        "q": [0.0, 0.0, 0.0, 1.0],
        "frame": "world_to_cam",
    }
    response: dict[str, Any] = {
        "schemaVersion": "byes.slam_pose.v1",
        "runId": run_id or None,
        "frameSeq": request.frameSeq,
        "backend": BACKEND,
        "model": MODEL_ID,
        "endpoint": endpoint_text,
        "trackingState": tracking_state,
        "pose": pose,
    }

    if isinstance(frame_payload, dict):
        tracking_state = _normalize_tracking_state(frame_payload.get("trackingState"))
        pose_norm, pose_warn = _normalize_pose(frame_payload.get("pose"))
        if pose_norm is not None:
            response["trackingState"] = tracking_state
            response["pose"] = pose_norm
        warnings_count += int(pose_warn)
        map_id = frame_payload.get("mapId")
        map_id_text = str(map_id).strip() if map_id is not None else ""
        if map_id_text:
            response["mapId"] = map_id_text
        cov = frame_payload.get("cov")
        if isinstance(cov, dict):
            response["cov"] = cov
        frame_warnings = frame_payload.get("warningsCount")
        try:
            warnings_count += max(0, int(frame_warnings))
        except Exception:
            pass

    if warning:
        response["warning"] = warning
    if warnings_count > 0:
        response["warningsCount"] = int(warnings_count)
    return response

