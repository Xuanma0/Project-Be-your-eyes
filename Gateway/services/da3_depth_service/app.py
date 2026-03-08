from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel


APP_TITLE = "BYES DA3 Depth Service"
BACKEND = "da3"


class DepthRequest(BaseModel):
    image_b64: str | None = None
    frameSeq: int | None = None
    runId: str | None = None
    mode: str | None = None
    refViewStrategy: str | None = None
    pose: dict[str, Any] | None = None


app = FastAPI(title=APP_TITLE)
_DA3_RUNTIME_LOCK = threading.Lock()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_fixture_dir() -> Path:
    return _repo_root() / "Gateway" / "tests" / "fixtures" / "run_package_with_da3_fixture_depth_min"


def _fixture_path_from_dir(fixture_dir: Path) -> Path:
    return fixture_dir / "gt" / "depth_gt_v1.json"


def _model_id() -> str:
    return str(os.getenv("BYES_DA3_MODEL_ID", "da3-v1")).strip() or "da3-v1"


def _normalize_mode(raw: Any) -> str:
    value = str(raw or "").strip().lower() or "fixture"
    if value not in {"fixture", "da3"}:
        return "fixture"
    return value


def _normalize_grid(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if str(raw.get("format", "")).strip() != "grid_u16_mm_v1":
        return None
    if str(raw.get("unit", "")).strip().lower() != "mm":
        return None
    size_raw = raw.get("size")
    if not isinstance(size_raw, list) or len(size_raw) != 2:
        return None
    try:
        gw = int(size_raw[0])
        gh = int(size_raw[1])
    except Exception:
        return None
    if gw <= 0 or gh <= 0:
        return None
    values_raw = raw.get("values")
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


def _normalize_frame_rows(rows: list[Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            seq = int(row.get("frameSeq", row.get("seq")))
        except Exception:
            continue
        if seq <= 0:
            continue
        grid = _normalize_grid(row.get("grid"))
        if grid is None:
            continue
        payload: dict[str, Any] = {"grid": grid}
        try:
            image_width = int(row.get("imageWidth"))
            if image_width > 0:
                payload["imageWidth"] = image_width
        except Exception:
            pass
        try:
            image_height = int(row.get("imageHeight"))
            if image_height > 0:
                payload["imageHeight"] = image_height
        except Exception:
            pass
        out[seq] = payload
    return out


def _load_fixture_mapping(path: Path, default_run_id: str) -> tuple[dict[str, dict[int, dict[str, Any]]], int]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    mapping: dict[str, dict[int, dict[str, Any]]] = {}
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
        rows = payload.get("frames")
        if isinstance(rows, list):
            run_id = str(payload.get("runId", "")).strip() or default_run_id
            mapping[run_id] = _normalize_frame_rows(rows)
            return mapping, warnings_count

    raise ValueError("unsupported fixture payload format")


def _resolve_fixture_inputs() -> tuple[Path, Path]:
    fixture_dir_text = str(os.getenv("BYES_DA3_FIXTURE_DIR", "")).strip()
    fixture_path_text = str(os.getenv("BYES_DA3_FIXTURE_PATH", "")).strip()
    if fixture_dir_text:
        fixture_dir = Path(fixture_dir_text)
        return fixture_dir, _fixture_path_from_dir(fixture_dir)
    if fixture_path_text:
        fixture_path = Path(fixture_path_text)
        fixture_dir = fixture_path.parent.parent if fixture_path.parent.name.lower() == "gt" else fixture_path.parent
        return fixture_dir, fixture_path
    fixture_dir = _default_fixture_dir()
    return fixture_dir, _fixture_path_from_dir(fixture_dir)


def _decode_image_b64(value: str | None) -> bytes:
    text = str(value or "").strip()
    if not text:
        return b""
    return base64.b64decode(text, validate=False)


def _decode_image(value: str | None):
    from PIL import Image

    payload = _decode_image_b64(value)
    if not payload:
        raise ValueError("missing_image_b64")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.convert("RGB")
    except Exception as exc:
        raise ValueError("invalid_image_b64") from exc


def _stub_da3_grid(frame_seq: int | None) -> dict[str, Any]:
    seq = int(frame_seq or 1)
    gw = 4
    gh = 4
    base = 1200 + max(0, seq - 1) * 40
    values = [max(0, min(65535, base + idx * 8)) for idx in range(gw * gh)]
    return {"format": "grid_u16_mm_v1", "size": [gw, gh], "unit": "mm", "values": values}


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _resolve_runtime_device(requested: str | None) -> tuple[str, str | None, str | None]:
    import torch

    requested_text = str(requested or "").strip().lower() or "auto"
    if requested_text not in {"auto", "cpu", "cuda", "gpu"}:
        requested_text = "auto"
    if requested_text == "cpu":
        return "cpu", "forced_cpu", None
    try:
        if not torch.cuda.is_available():
            return "cpu", "cuda_unavailable", None
        device_name = str(torch.cuda.get_device_name(0) or "").strip() or None
        capability = torch.cuda.get_device_capability(0)
        capability_token = f"sm_{int(capability[0])}{int(capability[1])}"
        arch_list = {str(item).strip().lower() for item in torch.cuda.get_arch_list() if str(item).strip()}
        if arch_list and capability_token.lower() not in arch_list:
            return "cpu", f"cuda_arch_unsupported:{capability_token}", device_name
        return "cuda", "cuda_ok", device_name
    except Exception as exc:
        return "cpu", f"cuda_probe_failed:{exc.__class__.__name__}", None


def _resolve_model_dir(model_path_text: str | None) -> Path | None:
    text = str(model_path_text or "").strip()
    if not text:
        return None
    model_path = Path(text)
    if model_path.is_dir():
        return model_path
    if model_path.is_file():
        return model_path.parent
    return None


def _ensure_da3_runtime(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state.get("runtime")
    if isinstance(runtime, dict) and runtime.get("model") is not None:
        return runtime

    with _DA3_RUNTIME_LOCK:
        runtime = state.get("runtime")
        if isinstance(runtime, dict) and runtime.get("model") is not None:
            return runtime

        load_error = str(state.get("da3LoadError") or "").strip()
        if load_error:
            raise RuntimeError(load_error)

        from depth_anything_3.api import DepthAnything3

        selected_device, device_reason, device_name = _resolve_runtime_device(state.get("device"))
        model_dir = _resolve_model_dir(state.get("modelPath"))
        if model_dir is None:
            raise RuntimeError("invalid_model_dir")

        started = time.perf_counter()
        model = DepthAnything3.from_pretrained(str(model_dir))
        model = model.to(device=selected_device)
        model.eval()
        runtime = {
            "model": model,
            "device": selected_device,
            "deviceReason": device_reason,
            "deviceName": device_name,
            "modelDir": str(model_dir),
            "loadMs": int(max(0.0, (time.perf_counter() - started) * 1000.0)),
            "loadedAtMs": int(time.time() * 1000),
        }
        state["runtime"] = runtime
        state["actualDevice"] = selected_device
        state["deviceReason"] = device_reason
        state["deviceName"] = device_name
        state["da3Ready"] = True
        state["da3LoadError"] = None
        return runtime


def _depth_to_grid(depth_map: Any, *, grid_w: int, grid_h: int) -> dict[str, Any]:
    import numpy as np
    import torch
    import torch.nn.functional as F

    depth_array = np.asarray(depth_map, dtype=np.float32)
    if depth_array.ndim != 2:
        raise ValueError("invalid_depth_shape")
    depth_array = np.nan_to_num(depth_array, nan=0.0, posinf=65.535, neginf=0.0)
    tensor = torch.from_numpy(depth_array).unsqueeze(0).unsqueeze(0)
    resized = F.interpolate(
        tensor,
        size=(max(1, int(grid_h)), max(1, int(grid_w))),
        mode="bilinear",
        align_corners=False,
    )[0, 0].cpu().numpy()
    values_mm = np.clip(np.rint(resized * 1000.0), 0, 65535).astype(np.uint16)
    return {
        "format": "grid_u16_mm_v1",
        "size": [int(grid_w), int(grid_h)],
        "unit": "mm",
        "values": [int(item) for item in values_mm.reshape(-1).tolist()],
    }


def _load_state() -> dict[str, Any]:
    mode = _normalize_mode(os.getenv("BYES_DA3_MODE", "fixture"))
    expected_run_id = str(os.getenv("BYES_DA3_RUN_ID", "fixture-da3-depth")).strip() or "fixture-da3-depth"
    endpoint_override = str(os.getenv("BYES_DA3_ENDPOINT", "")).strip() or None
    timeout_ms = max(1, int(str(os.getenv("BYES_DA3_TIMEOUT_MS", "2000")).strip() or "2000"))
    model_id = _model_id()
    model_path_text = str(os.getenv("BYES_DA3_MODEL_PATH", "")).strip() or None
    device = str(os.getenv("BYES_DA3_DEVICE", "cpu")).strip() or "cpu"

    state: dict[str, Any] = {
        "mode": mode,
        "modelId": model_id,
        "endpoint": endpoint_override,
        "timeoutMs": timeout_ms,
        "device": device,
        "modelPath": model_path_text,
        "da3Ready": False,
        "da3LoadError": None,
        "actualDevice": None,
        "deviceReason": None,
        "deviceName": None,
        "fixtureDir": None,
        "fixturePath": None,
        "expectedRunId": expected_run_id,
        "mapping": {},
        "warningsCount": 0,
        "runtime": None,
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
        state["da3Ready"] = True
        return state

    if not model_path_text:
        state["da3LoadError"] = "missing_BYES_DA3_MODEL_PATH"
        return state
    model_path = Path(model_path_text)
    if not model_path.exists():
        state["da3LoadError"] = f"model_path_not_found:{model_path}"
        return state
    state["da3Ready"] = True
    return state


@app.on_event("startup")
def _startup() -> None:
    state = _load_state()
    app.state.da3_state = state
    eager_load = str(os.getenv("BYES_DA3_EAGER_LOAD", "1")).strip().lower() not in {"0", "false", "no", "off"}
    if eager_load and str(state.get("mode") or "") == "da3" and not state.get("da3LoadError"):
        try:
            _ensure_da3_runtime(state)
        except Exception as exc:
            state["da3LoadError"] = f"runtime_load_failed:{exc.__class__.__name__}:{exc}"


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    state = getattr(app.state, "da3_state", _load_state())
    mapping = state.get("mapping")
    mapping = mapping if isinstance(mapping, dict) else {}
    model_path = str(state.get("modelPath", "")).strip()
    model_path_exists = bool(model_path and Path(model_path).exists())
    return {
        "ok": True,
        "backend": BACKEND,
        "model": state.get("modelId"),
        "mode": state.get("mode"),
        "device": state.get("device"),
        "actualDevice": state.get("actualDevice"),
        "deviceReason": state.get("deviceReason"),
        "deviceName": state.get("deviceName"),
        "timeoutMs": int(state.get("timeoutMs", 0) or 0),
        "da3Ready": bool(state.get("da3Ready")),
        "da3LoadError": state.get("da3LoadError"),
        "modelPath": model_path or None,
        "modelPathExists": model_path_exists,
        "fixtureDir": state.get("fixtureDir"),
        "fixturePath": state.get("fixturePath"),
        "runIds": sorted(str(k) for k in mapping.keys()),
        "warningsCount": int(state.get("warningsCount", 0) or 0),
        "modelLoaded": bool(isinstance(state.get("runtime"), dict) and state["runtime"].get("model") is not None),
        "loadMs": (state.get("runtime") or {}).get("loadMs") if isinstance(state.get("runtime"), dict) else None,
    }


@app.post("/depth")
def depth_estimate(request: DepthRequest, raw_request: Request) -> dict[str, Any]:
    state = getattr(app.state, "da3_state", _load_state())
    mode = _normalize_mode(request.mode or state.get("mode"))
    warning: str | None = None
    warnings_count = int(state.get("warningsCount", 0) or 0)
    frame_payload: dict[str, Any] | None = None

    if mode == "da3":
        load_error = str(state.get("da3LoadError") or "").strip()
        if load_error:
            raise HTTPException(status_code=500, detail=f"da3_not_ready:{load_error}")
        try:
            image = _decode_image(request.image_b64)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            runtime = _ensure_da3_runtime(state)
        except Exception as exc:
            state["da3LoadError"] = f"runtime_load_failed:{exc.__class__.__name__}"
            raise HTTPException(status_code=500, detail=f"da3_not_ready:{exc}") from exc
        infer_started = time.perf_counter()
        process_res = max(128, _env_int("BYES_DA3_PROCESS_RES", 224))
        grid_w = max(8, _env_int("BYES_DA3_GRID_W", 64))
        grid_h = max(8, _env_int("BYES_DA3_GRID_H", 36))
        try:
            prediction = runtime["model"].inference(
                [image],
                process_res=process_res,
                ref_view_strategy=str(request.refViewStrategy or "").strip() or "saddle_balanced",
            )
            depth = prediction.depth[0]
            frame_payload = {
                "grid": _depth_to_grid(depth, grid_w=grid_w, grid_h=grid_h),
                "imageWidth": int(image.width),
                "imageHeight": int(image.height),
                "inferMs": int(max(0.0, (time.perf_counter() - infer_started) * 1000.0)),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"da3_infer_failed:{exc.__class__.__name__}:{exc}") from exc
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
                    frame_payload = run_map.get(int(frame_seq))
                    if not isinstance(frame_payload, dict):
                        warning = "frame_not_found"
                        warnings_count += 1

    endpoint = str(state.get("endpoint") or "").strip()
    if not endpoint:
        endpoint = str(raw_request.url).split("?", 1)[0]

    response: dict[str, Any] = {
        "backend": BACKEND,
        "model": str(state.get("modelId") or _model_id()),
        "endpoint": endpoint,
        "gridCount": 0,
        "valuesCount": 0,
    }
    meta: dict[str, Any] = {
        "provider": BACKEND,
    }
    if mode == "da3":
        response["device"] = str(state.get("actualDevice") or state.get("device") or "cpu")
        response["inferMs"] = int((frame_payload or {}).get("inferMs", 0) or 0)
        device_reason = str(state.get("deviceReason") or "").strip()
        if device_reason:
            response["deviceReason"] = device_reason
        model_dir = str(((state.get("runtime") or {}).get("modelDir")) or "").strip()
        if model_dir:
            meta["modelDir"] = model_dir
    ref_view_strategy = str(request.refViewStrategy or "").strip()
    if ref_view_strategy:
        meta["refViewStrategy"] = ref_view_strategy
    if request.pose is not None:
        meta["poseUsed"] = isinstance(request.pose, dict)
    elif ref_view_strategy:
        meta["poseUsed"] = False
    if isinstance(frame_payload, dict):
        grid = frame_payload.get("grid")
        if isinstance(grid, dict):
            response["grid"] = grid
            response["gridCount"] = 1
            values = grid.get("values")
            if isinstance(values, list):
                response["valuesCount"] = len(values)
        image_width = frame_payload.get("imageWidth")
        image_height = frame_payload.get("imageHeight")
        try:
            if image_width is not None and int(image_width) > 0:
                response["imageWidth"] = int(image_width)
        except Exception:
            pass
        try:
            if image_height is not None and int(image_height) > 0:
                response["imageHeight"] = int(image_height)
        except Exception:
            pass
    if warning:
        response["warning"] = warning
    if warnings_count > 0:
        response["warningsCount"] = int(warnings_count)
        meta["warningsCount"] = int(warnings_count)
    if meta:
        response["meta"] = meta
    return response
