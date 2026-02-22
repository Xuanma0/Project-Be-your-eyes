from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from byes.config import GatewayConfig


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _req_entry(
    *,
    req_id: str,
    kind: str,
    path_or_value: str | None,
    env_var: str | None,
    exists: bool,
    notes: str,
) -> dict[str, Any]:
    return {
        "id": req_id,
        "kind": kind,
        "pathOrValue": path_or_value,
        "envVar": env_var,
        "exists": bool(exists),
        "notes": notes,
    }


def _endpoint_requirement(req_id: str, env_var: str, endpoint_value: str | None, notes: str) -> dict[str, Any]:
    endpoint = _clean(endpoint_value)
    return _req_entry(
        req_id=req_id,
        kind="endpoint",
        path_or_value=endpoint,
        env_var=env_var,
        exists=bool(endpoint),
        notes=notes,
    )


def _env_requirement(req_id: str, env_var: str, notes: str) -> dict[str, Any]:
    value = _clean(os.getenv(env_var))
    return _req_entry(
        req_id=req_id,
        kind="env",
        path_or_value=("<set>" if value else None),
        env_var=env_var,
        exists=bool(value),
        notes=notes,
    )


def _file_requirement(req_id: str, env_var: str, notes: str) -> dict[str, Any]:
    path_text = _clean(os.getenv(env_var))
    exists = bool(path_text and Path(path_text).expanduser().exists())
    return _req_entry(
        req_id=req_id,
        kind="file",
        path_or_value=path_text,
        env_var=env_var,
        exists=exists,
        notes=notes,
    )


def _component(
    *,
    name: str,
    enabled: bool,
    provider: str | None,
    model_id: str | None,
    endpoint: str | None,
    required: list[dict[str, Any]],
    optional: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "enabled": bool(enabled),
        "provider": _clean(provider) or "none",
        "modelId": _clean(model_id),
        "endpoint": _clean(endpoint),
        "required": required,
        "optional": optional,
        "warnings": [str(item) for item in (warnings or []) if str(item).strip()],
    }


def _seg_component(config: GatewayConfig) -> dict[str, Any]:
    enabled = bool(config.inference_enable_seg)
    provider = str(config.inference_seg_backend or "mock").strip().lower() or "mock"
    endpoint = config.inference_seg_http_url if provider == "http" else None
    downstream = (
        _clean(os.getenv("BYES_SEG_HTTP_DOWNSTREAM"))
        or _clean(os.getenv("BYES_SERVICE_SEG_HTTP_DOWNSTREAM"))
        or "reference"
    )
    downstream = str(downstream).strip().lower() if downstream is not None else "reference"
    if downstream not in {"reference", "sam3"}:
        downstream = "reference"
    required: list[dict[str, Any]] = []
    optional = [
        _file_requirement(
            "seg_model_path",
            "BYES_SEG_MODEL_PATH",
            "Optional local segmentation model file path for non-http providers.",
        )
    ]
    warnings: list[str] = []
    if enabled and provider == "http":
        required.append(
            _endpoint_requirement(
                "seg_http_endpoint",
                "BYES_SEG_HTTP_URL",
                endpoint,
                "Segmentation HTTP backend endpoint.",
            )
        )
        if downstream == "sam3":
            required.append(
                _file_requirement(
                    "sam3_ckpt_path",
                    "BYES_SAM3_CKPT_PATH",
                    "SAM3 checkpoint path required when seg downstream is sam3.",
                )
            )
    if enabled and provider == "mock":
        warnings.append("seg enabled with mock provider (no real model inference).")
    if enabled and provider == "http" and downstream == "sam3":
        warnings.append("seg http downstream=sam3 requires local SAM3 checkpoint availability.")
    if enabled and provider == "http" and downstream == "reference":
        warnings.append("seg http downstream=reference uses fixture-backed segmentation service.")
    return _component(
        name="seg",
        enabled=enabled,
        provider=(f"{provider}:{downstream}" if provider == "http" else provider),
        model_id=config.inference_seg_model_id,
        endpoint=endpoint,
        required=required,
        optional=optional,
        warnings=warnings,
    )


def _depth_component(config: GatewayConfig) -> dict[str, Any]:
    enabled = bool(config.inference_enable_depth)
    provider = str(config.inference_depth_backend or "mock").strip().lower() or "mock"
    endpoint = config.inference_depth_http_url if provider == "http" else None
    downstream = (
        _clean(os.getenv("BYES_DEPTH_HTTP_DOWNSTREAM"))
        or _clean(os.getenv("BYES_SERVICE_DEPTH_HTTP_DOWNSTREAM"))
        or "reference"
    )
    downstream = str(downstream).strip().lower() if downstream is not None else "reference"
    if downstream not in {"reference", "da3"}:
        downstream = "reference"
    required: list[dict[str, Any]] = []
    optional = [
        _file_requirement(
            "depth_model_onnx",
            "BYES_SERVICE_DEPTH_ONNX_PATH",
            "Optional ONNX depth model path (used by inference_service depth provider=onnx).",
        )
    ]
    warnings: list[str] = []
    if enabled and provider == "http":
        required.append(
            _endpoint_requirement(
                "depth_http_endpoint",
                "BYES_DEPTH_HTTP_URL|BYES_SERVICE_DEPTH_ENDPOINT",
                endpoint,
                "Depth HTTP backend endpoint.",
            )
        )
        if downstream == "da3":
            required.append(
                _file_requirement(
                    "da3_model_path",
                    "BYES_DA3_MODEL_PATH",
                    "DA3 model path required when depth downstream is da3.",
                )
            )
    if enabled and provider == "mock":
        warnings.append("depth enabled with mock provider (no real model inference).")
    if enabled and provider == "http" and downstream == "da3":
        warnings.append("depth http downstream=da3 requires local DA3 model availability.")
    if enabled and provider == "http" and downstream == "reference":
        warnings.append("depth http downstream=reference uses fixture-backed depth service.")
    return _component(
        name="depth",
        enabled=enabled,
        provider=(f"{provider}:{downstream}" if provider == "http" else provider),
        model_id=config.inference_depth_model_id,
        endpoint=endpoint,
        required=required,
        optional=optional,
        warnings=warnings,
    )


def _ocr_component(config: GatewayConfig) -> dict[str, Any]:
    enabled = bool(config.inference_enable_ocr)
    provider = str(config.inference_ocr_backend or "mock").strip().lower() or "mock"
    endpoint = config.inference_ocr_http_url if provider == "http" else None
    required: list[dict[str, Any]] = []
    optional = [
        _file_requirement(
            "ocr_model_path",
            "BYES_OCR_MODEL_PATH",
            "Optional local OCR model path for non-http providers.",
        )
    ]
    warnings: list[str] = []
    if enabled and provider == "http":
        required.append(
            _endpoint_requirement(
                "ocr_http_endpoint",
                "BYES_OCR_HTTP_URL|BYES_SERVICE_OCR_ENDPOINT",
                endpoint,
                "OCR HTTP backend endpoint.",
            )
        )
    if enabled and provider == "mock":
        warnings.append("ocr enabled with mock provider (no real model inference).")
    return _component(
        name="ocr",
        enabled=enabled,
        provider=provider,
        model_id=config.inference_ocr_model_id,
        endpoint=endpoint,
        required=required,
        optional=optional,
        warnings=warnings,
    )


def _risk_component(config: GatewayConfig) -> dict[str, Any]:
    enabled = bool(config.inference_enable_risk)
    provider = str(config.inference_risk_backend or "mock").strip().lower() or "mock"
    endpoint = config.inference_risk_http_url if provider == "http" else None
    required: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []
    warnings: list[str] = []
    if enabled and provider == "http":
        required.append(
            _endpoint_requirement(
                "risk_http_endpoint",
                "BYES_RISK_HTTP_URL",
                endpoint,
                "Risk HTTP backend endpoint.",
            )
        )
    if enabled and provider == "mock":
        warnings.append("risk enabled with mock provider (no real model inference).")
    return _component(
        name="risk",
        enabled=enabled,
        provider=provider,
        model_id=config.inference_risk_model_id,
        endpoint=endpoint,
        required=required,
        optional=optional,
        warnings=warnings,
    )


def _planner_component() -> dict[str, Any]:
    provider = str(os.getenv("BYES_PLANNER_BACKEND", "mock")).strip().lower() or "mock"
    endpoint = _clean(os.getenv("BYES_PLANNER_ENDPOINT"))
    enabled = True
    required: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []
    warnings: list[str] = []

    if provider == "http":
        required.append(
            _endpoint_requirement(
                "planner_http_endpoint",
                "BYES_PLANNER_ENDPOINT",
                endpoint,
                "Planner HTTP endpoint.",
            )
        )
    elif provider == "llm":
        required.append(_env_requirement("openai_api_key", "OPENAI_API_KEY", "OpenAI API key for llm planner backend."))
        optional.append(_env_requirement("openai_model", "OPENAI_MODEL", "Optional OpenAI model override."))
    elif provider == "mock":
        warnings.append("planner running in mock mode.")

    return _component(
        name="planner",
        enabled=enabled,
        provider=provider,
        model_id=_clean(os.getenv("BYES_PLANNER_MODEL")) or "reference-planner-v1",
        endpoint=endpoint,
        required=required,
        optional=optional,
        warnings=warnings,
    )


def _slam_component(config: GatewayConfig) -> dict[str, Any]:
    enabled = bool(config.inference_enable_slam)
    provider = str(config.inference_slam_backend or "mock").strip().lower() or "mock"
    endpoint = config.inference_slam_http_url if provider == "http" else None
    required: list[dict[str, Any]] = []
    optional = [
        _file_requirement(
            "slam_model_path",
            "BYES_SLAM_MODEL_PATH",
            "Optional local SLAM model path for non-http providers.",
        )
    ]
    warnings: list[str] = []
    if enabled and provider == "http":
        required.append(
            _endpoint_requirement(
                "slam_http_endpoint",
                "BYES_SLAM_HTTP_URL|BYES_SERVICE_SLAM_ENDPOINT",
                endpoint,
                "SLAM HTTP backend endpoint.",
            )
        )
    if enabled and provider == "mock":
        warnings.append("slam enabled with mock provider (no real SLAM backend).")
    return _component(
        name="slam",
        enabled=enabled,
        provider=provider,
        model_id=config.inference_slam_model_id,
        endpoint=endpoint,
        required=required,
        optional=optional,
        warnings=warnings,
    )


def _placeholder_component(name: str, *, enabled: bool = False) -> dict[str, Any]:
    warnings = ["placeholder component; no dedicated runtime service configured."]
    return _component(
        name=name,
        enabled=enabled,
        provider="none",
        model_id=None,
        endpoint=None,
        required=[],
        optional=[],
        warnings=warnings,
    )


def build_model_manifest(config: GatewayConfig) -> dict[str, Any]:
    components = [
        _seg_component(config),
        _depth_component(config),
        _ocr_component(config),
        _risk_component(config),
        _slam_component(config),
        _planner_component(),
        _placeholder_component("tts", enabled=_env_bool("BYES_ENABLE_TTS", False)),
    ]

    enabled_total = 0
    missing_required_total = 0
    for component in components:
        enabled = bool(component.get("enabled"))
        if enabled:
            enabled_total += 1
            for req in component.get("required", []):
                if not isinstance(req, dict):
                    continue
                if not bool(req.get("exists")):
                    missing_required_total += 1

    return {
        "schemaVersion": "byes.models.v1",
        "generatedAtMs": _now_ms(),
        "summary": {
            "componentsTotal": int(len(components)),
            "enabledTotal": int(enabled_total),
            "missingRequiredTotal": int(missing_required_total),
        },
        "components": components,
    }
