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


APP_TITLE = "BYES SAM3 Segmentation Service"
BACKEND = "sam3"


class SegRequest(BaseModel):
    runId: str | None = None
    frameSeq: int | None = None
    image_b64: str | None = None
    targets: list[str] | None = None
    prompt: dict[str, Any] | None = None
    tracking: bool | None = None
    mode: str | None = None


app = FastAPI(title=APP_TITLE)
_SAM3_RUNTIME_LOCK = threading.Lock()
_SAM3_CPU_PATCHED = False


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
    track_id_raw = raw.get("trackId")
    if isinstance(track_id_raw, str):
        track_id = track_id_raw.strip()
        if track_id:
            out["trackId"] = track_id
    track_state_raw = raw.get("trackState")
    if track_state_raw is None:
        out["trackState"] = None
    elif isinstance(track_state_raw, str):
        track_state = track_state_raw.strip().lower()
        if track_state in {"init", "track", "lost"}:
            out["trackState"] = track_state
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


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _decode_image_b64(image_b64: str | None):
    from PIL import Image

    text = str(image_b64 or "").strip()
    if not text:
        raise ValueError("missing_image_b64")
    try:
        payload = base64.b64decode(text, validate=False)
    except Exception as exc:
        raise ValueError("invalid_image_b64") from exc
    with Image.open(io.BytesIO(payload)) as image:
        return image.convert("RGB")


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


def _build_warmup_image(size: int):
    from PIL import Image, ImageDraw

    safe_size = max(64, min(256, int(size)))
    image = Image.new("RGB", (safe_size, safe_size), color=(36, 36, 36))
    draw = ImageDraw.Draw(image)
    inset = max(8, safe_size // 8)
    draw.rectangle(
        (inset, inset, safe_size - inset, safe_size - inset),
        outline=(240, 240, 240),
        fill=(96, 96, 96),
        width=max(2, safe_size // 32),
    )
    return image


def _warmup_sam3_processor(processor: Any) -> int:
    warmup_started = time.perf_counter()
    warmup_image = _build_warmup_image(_env_int("BYES_SAM3_WARMUP_IMAGE_SIZE", 160))
    warmup_prompt = str(os.getenv("BYES_SAM3_WARMUP_PROMPT", "object")).strip() or "object"
    state_payload = processor.set_image(warmup_image)
    processor.reset_all_prompts(state_payload)
    processor.set_text_prompt(warmup_prompt, state=state_payload)
    return int(max(0.0, (time.perf_counter() - warmup_started) * 1000.0))


def _patch_sam3_for_cpu() -> None:
    global _SAM3_CPU_PATCHED
    if _SAM3_CPU_PATCHED:
        return

    import torch
    import torchvision
    import sam3.model_builder as model_builder
    from sam3.model.box_ops import box_cxcywh_to_xyxy
    from sam3.model.decoder import TransformerDecoder
    from sam3.model.geometry_encoders import SequenceGeometryEncoder
    from sam3.model.position_encoding import PositionEmbeddingSine

    def safe_position_encoding(precompute_resolution=None):
        return PositionEmbeddingSine(
            num_pos_feats=256,
            normalize=True,
            scale=None,
            temperature=10000,
            precompute_resolution=None,
        )

    def safe_get_coords(height, width, device):
        return (
            torch.arange(0, height, device="cpu", dtype=torch.float32) / max(1, int(height)),
            torch.arange(0, width, device="cpu", dtype=torch.float32) / max(1, int(width)),
        )

    def safe_encode_boxes(self, boxes, boxes_mask, boxes_labels, img_feats):
        boxes_embed = None
        n_boxes, batch_size = boxes.shape[:2]

        if self.boxes_direct_project is not None:
            boxes_embed = self.boxes_direct_project(boxes)

        if self.boxes_pool_project is not None:
            feat_h, feat_w = img_feats.shape[-2:]
            boxes_xyxy = box_cxcywh_to_xyxy(boxes)
            scale = torch.tensor(
                [feat_w, feat_h, feat_w, feat_h],
                dtype=boxes_xyxy.dtype,
                device=boxes_xyxy.device,
            ).view(1, 1, 4)
            boxes_xyxy = boxes_xyxy * scale
            sampled = torchvision.ops.roi_align(
                img_feats,
                boxes_xyxy.float().transpose(0, 1).unbind(0),
                self.roi_size,
            )
            projected = self.boxes_pool_project(sampled)
            projected = projected.view(batch_size, n_boxes, self.d_model).transpose(0, 1)
            boxes_embed = projected if boxes_embed is None else boxes_embed + projected

        if self.boxes_pos_enc_project is not None:
            cx, cy, w, h = boxes.unbind(-1)
            encoded = self.pos_enc.encode_boxes(cx.flatten(), cy.flatten(), w.flatten(), h.flatten())
            encoded = encoded.view(boxes.shape[0], boxes.shape[1], encoded.shape[-1])
            projected = self.boxes_pos_enc_project(encoded)
            boxes_embed = projected if boxes_embed is None else boxes_embed + projected

        type_embed = self.label_embed(boxes_labels.long())
        return type_embed + boxes_embed, boxes_mask

    torch.cuda.is_available = lambda: False  # type: ignore[assignment]
    model_builder._create_position_encoding = safe_position_encoding
    TransformerDecoder._get_coords = staticmethod(safe_get_coords)
    SequenceGeometryEncoder._encode_boxes = safe_encode_boxes
    _SAM3_CPU_PATCHED = True


def _build_sam3_runtime(
    state: dict[str, Any],
    *,
    candidate_device: str,
    device_reason: str | None,
    device_name: str | None,
) -> dict[str, Any]:
    import torch
    import sam3.model_builder as model_builder
    from sam3.model.sam3_image_processor import Sam3Processor

    if candidate_device == "cpu":
        _patch_sam3_for_cpu()

    started = time.perf_counter()
    model = model_builder.build_sam3_image_model(
        device=candidate_device,
        checkpoint_path=state.get("ckptPath"),
        load_from_HF=False,
    )
    processor = Sam3Processor(
        model,
        resolution=max(128, _env_int("BYES_SAM3_RESOLUTION", 1008)),
        device=candidate_device,
        confidence_threshold=max(0.0, min(1.0, _env_float("BYES_SAM3_CONF_THRESH", 0.5))),
    )
    warmup_ms = _warmup_sam3_processor(processor)
    return {
        "processor": processor,
        "device": candidate_device,
        "deviceReason": device_reason,
        "deviceName": device_name,
        "loadMs": int(max(0.0, (time.perf_counter() - started) * 1000.0)),
        "warmupMs": warmup_ms,
        "loadedAtMs": int(time.time() * 1000),
        "torchVersion": getattr(torch, "__version__", None),
    }


def _ensure_sam3_runtime(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state.get("runtime")
    if isinstance(runtime, dict) and runtime.get("processor") is not None:
        return runtime

    with _SAM3_RUNTIME_LOCK:
        runtime = state.get("runtime")
        if isinstance(runtime, dict) and runtime.get("processor") is not None:
            return runtime

        load_error = str(state.get("sam3LoadError") or "").strip()
        if load_error:
            raise RuntimeError(load_error)

        import torch

        selected_device, resolved_reason, device_name = _resolve_runtime_device(state.get("device"))
        final_runtime: dict[str, Any] | None = None
        fallback_reason = resolved_reason

        if selected_device == "cuda":
            try:
                final_runtime = _build_sam3_runtime(
                    state,
                    candidate_device="cuda",
                    device_reason="cuda_warmup_ok",
                    device_name=device_name,
                )
            except Exception as exc:
                fallback_reason = f"cuda_warmup_failed:{exc.__class__.__name__}"
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass

        if final_runtime is None:
            final_runtime = _build_sam3_runtime(
                state,
                candidate_device="cpu",
                device_reason=fallback_reason,
                device_name=device_name,
            )

        state["runtime"] = final_runtime
        state["actualDevice"] = final_runtime.get("device")
        state["deviceReason"] = final_runtime.get("deviceReason")
        state["deviceName"] = final_runtime.get("deviceName")
        state["sam3Ready"] = True
        state["sam3LoadError"] = None
        return final_runtime


def _candidate_prompts(targets: list[str], prompt: dict[str, Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: Any) -> None:
        text = str(raw or "").strip()
        key = text.lower()
        if not text or key in seen:
            return
        seen.add(key)
        out.append(text)

    if isinstance(prompt, dict):
        prompt_text = str(prompt.get("text", "")).strip()
        if prompt_text:
            add(prompt_text)
        prompt_targets = prompt.get("targets")
        if isinstance(prompt_targets, list):
            for item in prompt_targets:
                add(item)
    for item in targets:
        add(item)

    fallback_prompt = str(os.getenv("BYES_SAM3_DEFAULT_PROMPT", "")).strip()
    if fallback_prompt:
        add(fallback_prompt)
    return out


def _encode_rle_mask(raw_mask: Any) -> dict[str, Any] | None:
    import numpy as np

    mask = raw_mask
    if hasattr(mask, "detach"):
        mask = mask.detach()
    if hasattr(mask, "cpu"):
        mask = mask.cpu()
    if hasattr(mask, "numpy"):
        mask = mask.numpy()
    mask_array = np.asarray(mask)
    if mask_array.ndim == 3 and mask_array.shape[0] == 1:
        mask_array = mask_array[0]
    if mask_array.ndim != 2:
        return None
    bool_mask = mask_array.astype(bool, copy=False)
    height, width = bool_mask.shape
    flat = bool_mask.reshape(-1)
    counts: list[int] = []
    current = False
    run_length = 0
    for value in flat:
        bit = bool(value)
        if bit == current:
            run_length += 1
            continue
        counts.append(run_length)
        current = bit
        run_length = 1
    counts.append(run_length)
    return {"format": "rle_v1", "size": [int(height), int(width)], "counts": [int(item) for item in counts]}


def _segment_from_output(prompt_text: str, output: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    import numpy as np

    masks = output.get("masks")
    boxes = output.get("boxes")
    scores = output.get("scores")
    if masks is None or boxes is None or scores is None:
        return []

    if hasattr(scores, "detach"):
        scores = scores.detach()
    if hasattr(scores, "cpu"):
        scores = scores.cpu()
    if hasattr(scores, "numpy"):
        scores = scores.numpy()
    scores_array = np.asarray(scores, dtype=np.float32).reshape(-1)
    if scores_array.size == 0:
        return []

    if hasattr(boxes, "detach"):
        boxes = boxes.detach()
    if hasattr(boxes, "cpu"):
        boxes = boxes.cpu()
    if hasattr(boxes, "numpy"):
        boxes = boxes.numpy()
    boxes_array = np.asarray(boxes, dtype=np.float32)

    if hasattr(masks, "detach"):
        masks = masks.detach()
    if hasattr(masks, "cpu"):
        masks = masks.cpu()
    if hasattr(masks, "numpy"):
        masks = masks.numpy()
    masks_array = np.asarray(masks)

    order = list(np.argsort(scores_array)[::-1])
    segments: list[dict[str, Any]] = []
    for idx in order[: max(1, int(limit))]:
        bbox = _normalize_bbox(boxes_array[idx].tolist() if idx < len(boxes_array) else None)
        mask = _encode_rle_mask(masks_array[idx] if idx < len(masks_array) else None)
        if bbox is None or mask is None:
            continue
        segments.append(
            {
                "label": str(prompt_text).strip().lower() or "segment",
                "score": max(0.0, min(1.0, float(scores_array[idx]))),
                "bbox": bbox,
                "mask": mask,
            }
        )
    return segments


def _load_state() -> dict[str, Any]:
    mode = _normalize_mode(os.getenv("BYES_SAM3_MODE", "fixture"))
    expected_run_id = str(os.getenv("BYES_SAM3_RUN_ID", "fixture-seg-gt")).strip() or "fixture-seg-gt"
    endpoint_override = str(os.getenv("BYES_SAM3_ENDPOINT", "")).strip() or None
    timeout_ms = max(1, int(str(os.getenv("BYES_SAM3_TIMEOUT_MS", "2000")).strip() or "2000"))
    model_id = _now_model_id()
    ckpt_path = str(os.getenv("BYES_SAM3_CKPT_PATH", "")).strip() or None
    device = str(os.getenv("BYES_SAM3_DEVICE", "auto")).strip() or "auto"

    state: dict[str, Any] = {
        "mode": mode,
        "modelId": model_id,
        "endpoint": endpoint_override,
        "timeoutMs": timeout_ms,
        "device": device,
        "ckptPath": ckpt_path,
        "sam3Ready": False,
        "sam3LoadError": None,
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
    state = _load_state()
    app.state.sam3_state = state
    eager_load = str(os.getenv("BYES_SAM3_EAGER_LOAD", "1")).strip().lower() not in {"0", "false", "no", "off"}
    if eager_load and str(state.get("mode") or "") == "sam3" and not state.get("sam3LoadError"):
        try:
            _ensure_sam3_runtime(state)
        except Exception as exc:
            state["sam3LoadError"] = f"runtime_load_failed:{exc.__class__.__name__}:{exc}"


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
        "actualDevice": state.get("actualDevice"),
        "deviceReason": state.get("deviceReason"),
        "deviceName": state.get("deviceName"),
        "ckptPath": state.get("ckptPath"),
        "fixtureDir": state.get("fixtureDir"),
        "fixturePath": state.get("fixturePath"),
        "runIds": sorted(str(k) for k in mapping.keys()),
        "warningsCount": int(state.get("warningsCount", 0) or 0),
        "modelLoaded": bool(isinstance(state.get("runtime"), dict) and state["runtime"].get("processor") is not None),
        "loadMs": (state.get("runtime") or {}).get("loadMs") if isinstance(state.get("runtime"), dict) else None,
        "warmupMs": (state.get("runtime") or {}).get("warmupMs") if isinstance(state.get("runtime"), dict) else None,
    }


@app.post("/seg")
def segment(request: SegRequest, raw_request: Request) -> dict[str, Any]:
    state = getattr(app.state, "sam3_state", _load_state())
    mode = _normalize_mode(request.mode or state.get("mode"))
    warnings_count = int(state.get("warningsCount", 0) or 0)
    warning: str | None = None
    segments: list[dict[str, Any]] = []
    tracking_used = bool(request.tracking)

    targets = _normalize_targets(request.targets)
    prompt_targets = _prompt_targets(request.prompt)
    label_filter = sorted(set(targets + prompt_targets))

    if mode == "sam3":
        load_error = str(state.get("sam3LoadError") or "").strip()
        if load_error:
            raise HTTPException(status_code=500, detail=f"sam3_not_ready:{load_error}")
        try:
            image = _decode_image_b64(request.image_b64)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            runtime = _ensure_sam3_runtime(state)
        except Exception as exc:
            state["sam3LoadError"] = f"runtime_load_failed:{exc.__class__.__name__}"
            raise HTTPException(status_code=500, detail=f"sam3_not_ready:{exc}") from exc

        prompt_candidates = _candidate_prompts(targets, request.prompt)
        if not prompt_candidates:
            warning = "no_prompt_candidates"
            warnings_count += 1
        else:
            processor = runtime.get("processor")
            infer_started = time.perf_counter()
            max_segments = max(1, _env_int("BYES_SAM3_MAX_SEGMENTS", 12))
            max_prompts = max(1, _env_int("BYES_SAM3_MAX_PROMPTS", 3))
            try:
                state_payload = processor.set_image(image)
                for prompt_text in prompt_candidates[:max_prompts]:
                    processor.reset_all_prompts(state_payload)
                    output = processor.set_text_prompt(prompt_text, state=state_payload)
                    segments.extend(_segment_from_output(prompt_text, output, max_segments))
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"sam3_infer_failed:{exc.__class__.__name__}:{exc}") from exc
            if not segments:
                warning = "no_segments"
                warnings_count += 1
            infer_ms = int(max(0.0, (time.perf_counter() - infer_started) * 1000.0))
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
        "trackingUsed": tracking_used,
    }
    if mode == "sam3":
        response["device"] = str(state.get("actualDevice") or state.get("device") or "cpu")
        response["inferMs"] = int(locals().get("infer_ms", 0) or 0)
        device_reason = str(state.get("deviceReason") or "").strip()
        if device_reason:
            response["deviceReason"] = device_reason
    if targets:
        response["targetsCount"] = len(targets)
        response["targetsUsed"] = targets
    if warning:
        response["warning"] = warning
    if warnings_count > 0:
        response["warningsCount"] = int(warnings_count)
    return response
