from __future__ import annotations

import base64
import io
import os
import random
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel

from services.inference_service.providers.base import OCRProvider, RiskProvider, SegProvider, DetProvider, DepthProvider, SlamProvider
from services.inference_service.providers import (
    create_ocr_provider,
    create_seg_provider,
    create_det_provider,
    create_depth_provider,
    create_slam_provider,
)
from services.inference_service.providers.depth_base import DepthProvider as RiskDepthProvider
from services.inference_service.providers.depth_none import NoneDepthProvider
from services.inference_service.providers.depth_synth import SynthDepthProvider
from services.inference_service.providers.onnx_depth import OnnxDepthProvider
from services.inference_service.providers.heuristic_risk import HeuristicRiskProvider
from services.inference_service.providers.reference_risk import ReferenceRiskProvider
from services.inference_service.providers.utils import postprocess_text


def _now_ms() -> int:
    return int(time.time() * 1000)


class InferenceRequest(BaseModel):
    image_b64: str
    frameSeq: int | None = None
    runId: str | None = None
    targets: list[str] | None = None
    prompt: dict[str, Any] | None = None
    tracking: bool | None = None
    refViewStrategy: str | None = None
    pose: dict[str, Any] | None = None
    riskThresholds: dict[str, float] | None = None


app = FastAPI(title="BYES Reference Inference Service")
_OCR_PROVIDER: OCRProvider | None = None
_RISK_PROVIDER: RiskProvider | None = None
_DEPTH_PROVIDER: RiskDepthProvider | None = None
_SEG_PROVIDER: SegProvider | None = None
_DET_PROVIDER: DetProvider | None = None
_TOOL_DEPTH_PROVIDER: DepthProvider | None = None
_SLAM_PROVIDER: SlamProvider | None = None


def _decode_image_b64(value: str) -> bytes:
    text = str(value or "").strip()
    if not text:
        return b""
    try:
        return base64.b64decode(text, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_image_b64:{exc.__class__.__name__}") from exc


def _decode_pil_image(value: str) -> Image.Image:
    raw = _decode_image_b64(value)
    if not raw:
        raise HTTPException(status_code=400, detail="empty_image_payload")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_image:{exc.__class__.__name__}") from exc


def _select_ocr_provider() -> OCRProvider:
    name = str(os.getenv("BYES_SERVICE_OCR_PROVIDER", "mock")).strip().lower()
    return create_ocr_provider(name=name)


def _select_risk_provider() -> RiskProvider:
    name = str(os.getenv("BYES_SERVICE_RISK_PROVIDER", "reference")).strip().lower()
    if name == "heuristic":
        return HeuristicRiskProvider(depth_provider=get_depth_provider())
    return ReferenceRiskProvider()


def _select_depth_provider() -> RiskDepthProvider:
    name = str(os.getenv("BYES_SERVICE_DEPTH_PROVIDER", "none")).strip().lower()
    if name == "da3":
        # DA3 often runs as a dedicated service for /depth; for risk-side local heuristics,
        # try ONNX depth if configured, otherwise keep service boot-safe.
        try:
            return OnnxDepthProvider()
        except Exception:
            return NoneDepthProvider()
    if name == "synth":
        return SynthDepthProvider()
    if name == "onnx":
        return OnnxDepthProvider()
    if name == "midas":
        try:
            from services.inference_service.providers.depth_midas import MidasOnnxDepthProvider
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"depth_provider_import_failed:{exc.__class__.__name__}") from exc
        return MidasOnnxDepthProvider()
    return NoneDepthProvider()


def _select_seg_provider() -> SegProvider:
    name = str(os.getenv("BYES_SERVICE_SEG_PROVIDER", "mock")).strip().lower()
    return create_seg_provider(name=name)


def _select_det_provider() -> DetProvider:
    name = str(os.getenv("BYES_SERVICE_DET_PROVIDER", "mock")).strip().lower()
    return create_det_provider(name=name)


def _select_tool_depth_provider() -> DepthProvider:
    name = str(os.getenv("BYES_SERVICE_DEPTH_PROVIDER", "mock")).strip().lower()
    if name not in {"mock", "http", "da3", "onnx", "none"}:
        name = str(os.getenv("BYES_SERVICE_DEPTH_TOOL_PROVIDER", "mock")).strip().lower()
    return create_depth_provider(name=name or "mock")


def _select_slam_provider() -> SlamProvider:
    name = str(os.getenv("BYES_SERVICE_SLAM_PROVIDER", "mock")).strip().lower()
    return create_slam_provider(name=name)


def get_ocr_provider() -> OCRProvider:
    global _OCR_PROVIDER  # noqa: PLW0603
    if _OCR_PROVIDER is None:
        _OCR_PROVIDER = _select_ocr_provider()
        print(f"[inference_service] selected OCR provider={_OCR_PROVIDER.name} model={_OCR_PROVIDER.model}")
    return _OCR_PROVIDER


def get_risk_provider() -> RiskProvider:
    global _RISK_PROVIDER  # noqa: PLW0603
    if _RISK_PROVIDER is None:
        _RISK_PROVIDER = _select_risk_provider()
        print(f"[inference_service] selected RISK provider={_RISK_PROVIDER.name} model={_RISK_PROVIDER.model}")
    return _RISK_PROVIDER


def get_depth_provider() -> RiskDepthProvider:
    global _DEPTH_PROVIDER  # noqa: PLW0603
    if _DEPTH_PROVIDER is None:
        _DEPTH_PROVIDER = _select_depth_provider()
        print(f"[inference_service] selected DEPTH provider={_DEPTH_PROVIDER.name} model={_DEPTH_PROVIDER.model}")
    return _DEPTH_PROVIDER


def get_seg_provider() -> SegProvider:
    global _SEG_PROVIDER  # noqa: PLW0603
    if _SEG_PROVIDER is None:
        _SEG_PROVIDER = _select_seg_provider()
        print(f"[inference_service] selected SEG provider={_SEG_PROVIDER.name} model={_SEG_PROVIDER.model}")
    return _SEG_PROVIDER


def get_det_provider() -> DetProvider:
    global _DET_PROVIDER  # noqa: PLW0603
    if _DET_PROVIDER is None:
        _DET_PROVIDER = _select_det_provider()
        print(f"[inference_service] selected DET provider={_DET_PROVIDER.name} model={_DET_PROVIDER.model}")
    return _DET_PROVIDER


def get_tool_depth_provider() -> DepthProvider:
    global _TOOL_DEPTH_PROVIDER  # noqa: PLW0603
    if _TOOL_DEPTH_PROVIDER is None:
        _TOOL_DEPTH_PROVIDER = _select_tool_depth_provider()
        print(
            f"[inference_service] selected DEPTH_TOOL provider={_TOOL_DEPTH_PROVIDER.name} model={_TOOL_DEPTH_PROVIDER.model}"
        )
    return _TOOL_DEPTH_PROVIDER


def get_slam_provider() -> SlamProvider:
    global _SLAM_PROVIDER  # noqa: PLW0603
    if _SLAM_PROVIDER is None:
        _SLAM_PROVIDER = _select_slam_provider()
        print(f"[inference_service] selected SLAM provider={_SLAM_PROVIDER.name} model={_SLAM_PROVIDER.model}")
    return _SLAM_PROVIDER


@app.on_event("startup")
def _startup_provider() -> None:
    get_depth_provider()
    get_tool_depth_provider()
    get_ocr_provider()
    get_risk_provider()
    get_seg_provider()
    get_det_provider()
    get_slam_provider()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    ocr_provider = get_ocr_provider()
    risk_provider = get_risk_provider()
    depth_provider = get_depth_provider()
    seg_provider = get_seg_provider()
    det_provider = get_det_provider()
    depth_tool_provider = get_tool_depth_provider()
    slam_provider = get_slam_provider()
    return {
        "ok": True,
        "ocrProvider": ocr_provider.name,
        "ocrModel": ocr_provider.model,
        "riskProvider": risk_provider.name,
        "riskModel": risk_provider.model,
        "depthProvider": depth_provider.name,
        "depthModel": depth_provider.model,
        "segProvider": seg_provider.name,
        "segModel": seg_provider.model,
        "detProvider": det_provider.name,
        "detModel": det_provider.model,
        "depthToolProvider": depth_tool_provider.name,
        "depthToolModel": depth_tool_provider.model,
        "slamProvider": slam_provider.name,
        "slamModel": slam_provider.model,
    }


@app.post("/ocr")
def infer_ocr(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    image = _decode_pil_image(request.image_b64)
    fail_prob = float(os.getenv("BYES_SERVICE_OCR_FAIL_PROB", os.getenv("BYES_REF_OCR_FAIL_PROB", "0")) or "0")
    if random.random() < max(0.0, min(1.0, fail_prob)):
        raise HTTPException(status_code=503, detail="ocr_unavailable")

    delay_ms = max(0, int(os.getenv("BYES_SERVICE_OCR_DELAY_MS", os.getenv("BYES_REF_OCR_DELAY_MS", "0")) or "0"))
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    provider = get_ocr_provider()
    try:
        try:
            result = provider.infer(
                image,
                request.frameSeq,
                request.runId,
                targets=request.targets,
                prompt=request.prompt,
            )
        except TypeError:
            result = provider.infer(image, request.frameSeq)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"ocr_infer_failed:{exc.__class__.__name__}") from exc

    lines_raw = result.get("lines")
    lines, warnings_count = _normalize_ocr_lines(
        lines_raw if isinstance(lines_raw, list) else [],
        image_width=int(result.get("imageWidth", image.width) or image.width),
        image_height=int(result.get("imageHeight", image.height) or image.height),
    )
    if not lines:
        text_fallback = postprocess_text(str(result.get("text", "")))
        if text_fallback:
            lines = [{"text": text_fallback}]
    if not lines:
        warnings_count += 1
    lines_count = len(lines)
    text = postprocess_text(" ".join(str(row.get("text", "")).strip() for row in lines if isinstance(row, dict)))
    model = str(result.get("model", provider.model)).strip() or provider.model
    latency_ms = max(0, _now_ms() - started)
    backend = str(result.get("backend", provider.name)).strip().lower() or provider.name
    endpoint = result.get("endpoint", getattr(provider, "endpoint", None))
    endpoint_text = str(endpoint).strip() if endpoint is not None else ""
    response: dict[str, Any] = {
        "schemaVersion": "byes.ocr.v1",
        "runId": request.runId,
        "frameSeq": request.frameSeq,
        "lines": lines,
        "linesCount": lines_count,
        "text": text,
        "latencyMs": latency_ms,
        "model": model,
        "backend": backend,
        "endpoint": endpoint_text or None,
        "imageWidth": int(result.get("imageWidth", image.width) or image.width),
        "imageHeight": int(result.get("imageHeight", image.height) or image.height),
    }
    try:
        warnings_count += max(0, int(result.get("warningsCount", 0) or 0))
    except Exception:
        pass
    if warnings_count > 0:
        response["warningsCount"] = int(warnings_count)
    return response


@app.post("/det")
def infer_det(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    image = _decode_pil_image(request.image_b64)
    provider = get_det_provider()
    targets = [str(item).strip() for item in (request.targets or []) if str(item).strip()]
    prompt = dict(request.prompt) if isinstance(request.prompt, dict) else None
    try:
        try:
            result = provider.infer(image, request.frameSeq, request.runId, targets=targets or None, prompt=prompt)
        except TypeError:
            result = provider.infer(image, request.frameSeq)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # Treat unexpected provider failures as temporary unavailability instead of hard 500.
        raise HTTPException(status_code=503, detail=f"det_infer_failed:{exc.__class__.__name__}") from exc

    model = str(result.get("model", provider.model)).strip() or provider.model
    latency_ms = max(0, _now_ms() - started)
    backend = str(result.get("backend", provider.name)).strip().lower() or provider.name
    endpoint = result.get("endpoint", getattr(provider, "endpoint", None))
    endpoint_text = str(endpoint).strip() if endpoint is not None else ""
    try:
        objects, warnings_count = _normalize_det_objects(result.get("objects"))
        top_k = _to_nonnegative_int(result.get("topK")) or 5
        response: dict[str, Any] = {
            "schemaVersion": "byes.det.v1",
            "runId": request.runId,
            "frameSeq": request.frameSeq,
            "objects": objects,
            "objectsCount": len(objects),
            "topK": max(1, top_k),
            "latencyMs": latency_ms,
            "model": model,
            "backend": backend,
            "endpoint": endpoint_text or None,
        }
        if "openVocab" in result:
            response["openVocab"] = bool(result.get("openVocab"))
        prompt_used = result.get("promptUsed")
        if isinstance(prompt_used, list):
            response["promptUsed"] = [str(item).strip() for item in prompt_used if str(item).strip()]
        image_width = _to_positive_int(result.get("imageWidth"))
        image_height = _to_positive_int(result.get("imageHeight"))
        if image_width is not None:
            response["imageWidth"] = image_width
        if image_height is not None:
            response["imageHeight"] = image_height
        if warnings_count > 0:
            response["warningsCount"] = warnings_count
        return response
    except Exception as exc:  # noqa: BLE001
        # Keep /det stable in pilot mode even when provider outputs malformed payloads.
        return {
            "schemaVersion": "byes.det.v1",
            "runId": request.runId,
            "frameSeq": request.frameSeq,
            "objects": [],
            "objectsCount": 0,
            "topK": 5,
            "latencyMs": latency_ms,
            "model": model,
            "backend": backend,
            "endpoint": endpoint_text or None,
            "warningsCount": 1,
            "warnings": [f"det_postprocess_failed:{exc.__class__.__name__}"],
        }


@app.post("/risk")
def infer_risk(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    request_started = time.perf_counter()
    decode_started = time.perf_counter()
    image = _decode_pil_image(request.image_b64)
    decode_ms = (time.perf_counter() - decode_started) * 1000.0
    fail_prob = float(os.getenv("BYES_SERVICE_RISK_FAIL_PROB", os.getenv("BYES_REF_RISK_FAIL_PROB", "0")) or "0")
    if random.random() < max(0.0, min(1.0, fail_prob)):
        raise HTTPException(status_code=503, detail="risk_unavailable")

    delay_ms = max(0, int(os.getenv("BYES_SERVICE_RISK_DELAY_MS", os.getenv("BYES_REF_RISK_DELAY_MS", "0")) or "0"))
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    provider = get_risk_provider()
    risk_thresholds_override: dict[str, float] | None = None
    if isinstance(request.riskThresholds, dict):
        risk_thresholds_override = {}
        for key, value in request.riskThresholds.items():
            try:
                risk_thresholds_override[str(key)] = float(value)
            except Exception:  # noqa: BLE001
                continue
    try:
        if risk_thresholds_override:
            try:
                result = provider.infer(image, request.frameSeq, thresholds_override=risk_thresholds_override)
            except TypeError:
                result = provider.infer(image, request.frameSeq)
        else:
            result = provider.infer(image, request.frameSeq)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"risk_infer_failed:{exc.__class__.__name__}") from exc

    model = str(result.get("model", provider.model)).strip() or provider.model
    hazards_raw = result.get("hazards", [])
    hazards: list[dict[str, Any]] = []
    if isinstance(hazards_raw, list):
        for item in hazards_raw:
            if not isinstance(item, dict):
                continue
            hazard_kind = str(item.get("hazardKind", "unknown")).strip() or "unknown"
            severity = str(item.get("severity", "warning")).strip().lower()
            if severity not in {"critical", "warning", "info"}:
                severity = "warning"
            normalized = {"hazardKind": hazard_kind, "severity": severity}
            if "score" in item:
                try:
                    normalized["score"] = float(item["score"])
                except Exception:  # noqa: BLE001
                    pass
            if isinstance(item.get("evidence"), dict):
                normalized["evidence"] = dict(item["evidence"])
            hazards.append(normalized)
    latency_ms = max(0, _now_ms() - started)
    response = {"hazards": hazards, "latencyMs": latency_ms, "model": model}
    if _env_bool("BYES_SERVICE_RISK_DEBUG", False):
        debug_payload = result.get("debug")
        merged_debug = dict(debug_payload) if isinstance(debug_payload, dict) else {}
        timings = merged_debug.get("timings")
        timings_payload = dict(timings) if isinstance(timings, dict) else {}
        timings_payload["decodeMs"] = round(max(0.0, decode_ms), 3)
        timings_payload["totalMs"] = round(max(0.0, (time.perf_counter() - request_started) * 1000.0), 3)
        merged_debug["timings"] = timings_payload
        response["debug"] = merged_debug
    return response


@app.post("/seg")
def infer_seg(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    image = _decode_pil_image(request.image_b64)
    provider = get_seg_provider()
    targets = [str(item).strip() for item in (request.targets or []) if str(item).strip()]
    prompt = dict(request.prompt) if isinstance(request.prompt, dict) else None
    tracking = bool(request.tracking) if isinstance(request.tracking, bool) else None
    try:
        try:
            result = provider.infer(
                image,
                request.frameSeq,
                request.runId,
                targets=targets or None,
                prompt=prompt,
                tracking=tracking,
            )
        except TypeError:
            try:
                result = provider.infer(
                    image,
                    request.frameSeq,
                    request.runId,
                    targets=targets or None,
                    prompt=prompt,
                )
            except TypeError:
                result = provider.infer(image, request.frameSeq, request.runId, targets=targets or None)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"seg_infer_failed:{exc.__class__.__name__}") from exc

    segments_raw = result.get("segments")
    segments_raw = segments_raw if isinstance(segments_raw, list) else []
    segments: list[dict[str, Any]] = []
    for item in segments_raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip() or "unknown"
        try:
            score = float(item.get("score", 0.0))
        except Exception:  # noqa: BLE001
            score = 0.0
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        normalized_bbox: list[float] = []
        try:
            normalized_bbox = [float(value) for value in bbox]
        except Exception:  # noqa: BLE001
            continue
        segment: dict[str, Any] = {"label": label, "score": score, "bbox": normalized_bbox}
        track_id_raw = item.get("trackId")
        if isinstance(track_id_raw, str):
            track_id = track_id_raw.strip()
            if track_id:
                segment["trackId"] = track_id
        track_state_raw = item.get("trackState")
        if track_state_raw is None:
            segment["trackState"] = None
        elif isinstance(track_state_raw, str):
            track_state = track_state_raw.strip().lower()
            if track_state in {"init", "track", "lost"}:
                segment["trackState"] = track_state
        mask = _normalize_seg_mask(item.get("mask"))
        if isinstance(mask, dict):
            segment["mask"] = mask
        segments.append(segment)

    model = str(result.get("model", provider.model)).strip() or provider.model
    latency_ms = max(0, _now_ms() - started)
    backend = str(result.get("backend", provider.name)).strip().lower() or provider.name
    endpoint = result.get("endpoint", provider.endpoint)
    endpoint_text = str(endpoint).strip() if endpoint is not None else ""
    response: dict[str, Any] = {
        "segments": segments,
        "latencyMs": latency_ms,
        "model": model,
        "backend": backend,
        "endpoint": endpoint_text or None,
    }
    if "targetsCount" in result:
        try:
            response["targetsCount"] = max(0, int(result.get("targetsCount", 0)))
        except Exception:  # noqa: BLE001
            response["targetsCount"] = len(targets)
    elif targets:
        response["targetsCount"] = len(targets)
    targets_used_raw = result.get("targetsUsed")
    if isinstance(targets_used_raw, list):
        response["targetsUsed"] = [str(item).strip() for item in targets_used_raw if str(item).strip()]
    elif targets:
        response["targetsUsed"] = targets
    downstream_value = result.get("downstream")
    if isinstance(downstream_value, str) and downstream_value.strip():
        response["downstream"] = downstream_value.strip().lower()
    tracking_used = result.get("trackingUsed")
    if isinstance(tracking_used, bool):
        response["trackingUsed"] = tracking_used
    elif isinstance(request.tracking, bool):
        response["trackingUsed"] = bool(request.tracking)
    return response


@app.post("/depth")
def infer_depth(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    image = _decode_pil_image(request.image_b64)
    provider = get_tool_depth_provider()
    targets = [str(item).strip() for item in (request.targets or []) if str(item).strip()]
    try:
        try:
            result = provider.infer(
                image,
                request.frameSeq,
                request.runId,
                targets=targets or None,
                ref_view_strategy=request.refViewStrategy,
                pose=request.pose,
            )
        except TypeError:
            result = provider.infer(image, request.frameSeq, request.runId, targets=targets or None)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"depth_infer_failed:{exc.__class__.__name__}") from exc

    grid = result.get("grid")
    grid = grid if isinstance(grid, dict) else None
    model = str(result.get("model", provider.model)).strip() or provider.model
    latency_ms = max(0, _now_ms() - started)
    backend = str(result.get("backend", provider.name)).strip().lower() or provider.name
    endpoint = result.get("endpoint", provider.endpoint)
    endpoint_text = str(endpoint).strip() if endpoint is not None else ""
    response: dict[str, Any] = {
        "latencyMs": latency_ms,
        "model": model,
        "backend": backend,
        "endpoint": endpoint_text or None,
        "gridCount": int(result.get("gridCount", 1 if isinstance(grid, dict) else 0) or 0),
        "valuesCount": int(result.get("valuesCount", 0) or 0),
    }
    image_width = result.get("imageWidth")
    image_height = result.get("imageHeight")
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
    if isinstance(grid, dict):
        response["grid"] = grid
    warnings_count = result.get("warningsCount")
    try:
        if warnings_count is not None and int(warnings_count) > 0:
            response["warningsCount"] = int(warnings_count)
    except Exception:
        pass
    meta_raw = result.get("meta")
    if isinstance(meta_raw, dict):
        response["meta"] = meta_raw
    downstream_value = result.get("downstream")
    if isinstance(downstream_value, str) and downstream_value.strip():
        response["downstream"] = downstream_value.strip().lower()
    return response


@app.post("/slam/pose")
def infer_slam_pose(request: InferenceRequest) -> dict[str, Any]:
    started = _now_ms()
    image = _decode_pil_image(request.image_b64)
    provider = get_slam_provider()
    targets = [str(item).strip() for item in (request.targets or []) if str(item).strip()]
    prompt = dict(request.prompt) if isinstance(request.prompt, dict) else None
    try:
        try:
            result = provider.infer(image, request.frameSeq, request.runId, targets=targets or None, prompt=prompt)
        except TypeError:
            result = provider.infer(image, request.frameSeq, request.runId, targets=targets or None)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"slam_infer_failed:{exc.__class__.__name__}") from exc

    pose = _normalize_slam_pose(result.get("pose"))
    tracking_state = _normalize_slam_tracking_state(result.get("trackingState"))
    if not isinstance(pose, dict) or not tracking_state:
        raise HTTPException(status_code=500, detail="slam_invalid_output")
    model = str(result.get("model", provider.model)).strip() or provider.model
    latency_ms = max(0, _now_ms() - started)
    backend = str(result.get("backend", provider.name)).strip().lower() or provider.name
    endpoint = result.get("endpoint", provider.endpoint)
    endpoint_text = str(endpoint).strip() if endpoint is not None else ""
    response: dict[str, Any] = {
        "schemaVersion": "byes.slam_pose.v1",
        "runId": request.runId,
        "frameSeq": request.frameSeq,
        "trackingState": tracking_state,
        "pose": pose,
        "latencyMs": latency_ms,
        "model": model,
        "backend": backend,
        "endpoint": endpoint_text or None,
    }
    map_id = result.get("mapId")
    map_id_text = str(map_id).strip() if map_id is not None else ""
    if map_id_text:
        response["mapId"] = map_id_text
    cov = result.get("cov")
    if isinstance(cov, dict):
        response["cov"] = cov
    warnings_count = _to_nonnegative_int(result.get("warningsCount"))
    if warnings_count > 0:
        response["warningsCount"] = warnings_count
    return response


# TODO: replace infer_ocr and infer_risk internals with real model pipelines:
# - OCR: PaddleOCR/Tesseract tokenizer + postprocess
# - Risk: depth model + hazard projection and thresholding


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _normalize_seg_mask(raw: Any) -> dict[str, Any] | None:
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


def _normalize_slam_tracking_state(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"tracking", "lost", "relocalized", "initializing"}:
        return value
    if value:
        return "unknown"
    return ""


def _normalize_slam_pose(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    t_raw = raw.get("t")
    q_raw = raw.get("q")
    if not isinstance(t_raw, list) or len(t_raw) != 3:
        return None
    if not isinstance(q_raw, list) or len(q_raw) != 4:
        return None
    try:
        t = [float(t_raw[0]), float(t_raw[1]), float(t_raw[2])]
        q = [float(q_raw[0]), float(q_raw[1]), float(q_raw[2]), float(q_raw[3])]
    except Exception:
        return None
    out: dict[str, Any] = {"t": t, "q": q}
    frame = str(raw.get("frame", "")).strip().lower()
    if frame in {"world_to_cam", "cam_to_world"}:
        out["frame"] = frame
    map_id = raw.get("mapId")
    map_id_text = str(map_id).strip() if map_id is not None else ""
    if map_id_text:
        out["mapId"] = map_id_text
    return out


def _normalize_ocr_lines(
    rows: list[Any],
    *,
    image_width: int | None,
    image_height: int | None,
) -> tuple[list[dict[str, Any]], int]:
    warnings_count = 0
    normalized: list[dict[str, Any]] = []
    width = int(image_width) if isinstance(image_width, int) and image_width > 0 else None
    height = int(image_height) if isinstance(image_height, int) and image_height > 0 else None
    for row in rows:
        if isinstance(row, str):
            text = postprocess_text(row)
            if not text:
                warnings_count += 1
                continue
            normalized.append({"text": text})
            continue
        if not isinstance(row, dict):
            warnings_count += 1
            continue
        text = postprocess_text(str(row.get("text", "")))
        if not text:
            warnings_count += 1
            continue
        out: dict[str, Any] = {"text": text}
        score_raw = row.get("score")
        if score_raw is not None:
            try:
                score = float(score_raw)
            except Exception:
                score = 0.0
                warnings_count += 1
            score_clamped = max(0.0, min(1.0, score))
            if score_clamped != score:
                warnings_count += 1
            out["score"] = score_clamped
        bbox_raw = row.get("bbox")
        if isinstance(bbox_raw, list) and len(bbox_raw) == 4:
            try:
                x0, y0, x1, y1 = [float(v) for v in bbox_raw]
            except Exception:
                warnings_count += 1
            else:
                if x0 > x1:
                    x0, x1 = x1, x0
                    warnings_count += 1
                if y0 > y1:
                    y0, y1 = y1, y0
                    warnings_count += 1
                if width is not None:
                    old = (x0, x1)
                    x0 = max(0.0, min(float(width), x0))
                    x1 = max(0.0, min(float(width), x1))
                    if old != (x0, x1):
                        warnings_count += 1
                if height is not None:
                    old = (y0, y1)
                    y0 = max(0.0, min(float(height), y0))
                    y1 = max(0.0, min(float(height), y1))
                    if old != (y0, y1):
                        warnings_count += 1
                if x1 <= x0:
                    x1 = x0 + 1.0
                    warnings_count += 1
                if y1 <= y0:
                    y1 = y0 + 1.0
                    warnings_count += 1
                out["bbox"] = [x0, y0, x1, y1]
        normalized.append(out)
    return normalized, warnings_count


def _normalize_det_objects(raw_objects: Any) -> tuple[list[dict[str, Any]], int]:
    warnings_count = 0
    objects: list[dict[str, Any]] = []
    if not isinstance(raw_objects, list):
        return objects, 1
    for row in raw_objects:
        if not isinstance(row, dict):
            warnings_count += 1
            continue
        label = str(row.get("label", "")).strip() or "unknown"
        conf = _to_float(row.get("conf"))
        if conf is None:
            warnings_count += 1
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        box_raw = row.get("box_xyxy")
        box_norm_raw = row.get("box_norm")
        if not (isinstance(box_raw, list) and len(box_raw) == 4):
            warnings_count += 1
            box_raw = [0.0, 0.0, 1.0, 1.0]
        try:
            box = [float(v) for v in box_raw]
        except Exception:
            warnings_count += 1
            box = [0.0, 0.0, 1.0, 1.0]
        normalized: dict[str, Any] = {"label": label, "conf": conf, "box_xyxy": box}
        if isinstance(box_norm_raw, list) and len(box_norm_raw) == 4:
            try:
                normalized["box_norm"] = [max(0.0, min(1.0, float(v))) for v in box_norm_raw]
            except Exception:
                warnings_count += 1
        mask = _normalize_det_mask(row.get("mask"))
        if isinstance(mask, dict):
            normalized["mask"] = mask
        elif row.get("mask") is not None:
            warnings_count += 1
        objects.append(normalized)
    objects.sort(key=lambda item: float(item.get("conf", 0.0)), reverse=True)
    return objects, warnings_count


def _normalize_det_mask(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    fmt = str(raw.get("format", "")).strip()
    if fmt != "polygon_v1":
        return None
    points_raw = raw.get("points")
    if not isinstance(points_raw, list):
        return None
    points: list[list[float]] = []
    for item in points_raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None
        try:
            x = float(item[0])
            y = float(item[1])
        except Exception:
            return None
        points.append([x, y])
    if len(points) < 3:
        return None
    out: dict[str, Any] = {"format": "polygon_v1", "points": points}
    points_norm_raw = raw.get("pointsNorm")
    if isinstance(points_norm_raw, list):
        points_norm: list[list[float]] = []
        for item in points_norm_raw:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            try:
                nx = max(0.0, min(1.0, float(item[0])))
                ny = max(0.0, min(1.0, float(item[1])))
            except Exception:
                continue
            points_norm.append([nx, ny])
        if points_norm:
            out["pointsNorm"] = points_norm
    return out


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _to_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    if parsed <= 0:
        return None
    return parsed


def _to_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0
