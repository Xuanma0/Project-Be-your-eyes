from __future__ import annotations

import base64
import os
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from byes.inference.backends.base import OCRResult, RiskResult, SegResult


def _now_ms() -> int:
    return int(time.time() * 1000)


class HttpOCRBackend:
    name = "http"

    def __init__(self, url: str, timeout_ms: int = 1500, model_id: str | None = None) -> None:
        self.url = str(url).strip()
        self.timeout_ms = max(1, int(timeout_ms))
        self.model_id = str(model_id or "").strip() or None
        self.endpoint = _sanitize_endpoint(self.url)

    async def infer(self, image_bytes: bytes, frame_seq: int | None, ts_ms: int) -> OCRResult:
        started = _now_ms()
        request_payload = {
            "frameSeq": frame_seq,
            "tsMs": ts_ms,
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
        }
        try:
            timeout_s = max(0.05, self.timeout_ms / 1000.0)
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(self.url, json=request_payload)
            latency = max(0, _now_ms() - started)
            if response.status_code >= 400:
                return OCRResult(
                    text="",
                    latency_ms=latency,
                    status="timeout" if response.status_code == 408 else "error",
                    error=f"http_{response.status_code}",
                    payload={"error": f"http_{response.status_code}"},
                )
            payload = response.json()
            self._update_model_id(payload)
            text = ""
            if isinstance(payload, dict):
                text = str(payload.get("text", payload.get("summary", "")) or "")
            return OCRResult(
                text=text,
                latency_ms=latency,
                status="ok",
                payload=_normalize_payload(payload),
                error=None,
            )
        except httpx.TimeoutException as exc:
            latency = max(0, _now_ms() - started)
            return OCRResult(
                text="",
                latency_ms=latency,
                status="timeout",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__},
            )
        except Exception as exc:  # noqa: BLE001
            latency = max(0, _now_ms() - started)
            return OCRResult(
                text="",
                latency_ms=latency,
                status="error",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__},
            )

    def _update_model_id(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        value = payload.get("model")
        if value is None:
            return
        text = str(value).strip()
        if text:
            self.model_id = text


class HttpRiskBackend:
    name = "http"

    def __init__(self, url: str, timeout_ms: int = 1200, model_id: str | None = None) -> None:
        self.url = str(url).strip()
        self.timeout_ms = max(1, int(timeout_ms))
        self.model_id = str(model_id or "").strip() or None
        self.endpoint = _sanitize_endpoint(self.url)

    async def infer(self, image_bytes: bytes, frame_seq: int | None, ts_ms: int) -> RiskResult:
        started = _now_ms()
        request_payload = {
            "frameSeq": frame_seq,
            "tsMs": ts_ms,
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
        }
        risk_thresholds = _collect_risk_threshold_overrides_from_env()
        if risk_thresholds:
            request_payload["riskThresholds"] = risk_thresholds
        try:
            timeout_s = max(0.05, self.timeout_ms / 1000.0)
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(self.url, json=request_payload)
            latency = max(0, _now_ms() - started)
            if response.status_code >= 400:
                return RiskResult(
                    hazards=[],
                    latency_ms=latency,
                    status="timeout" if response.status_code == 408 else "error",
                    error=f"http_{response.status_code}",
                    payload={"error": f"http_{response.status_code}"},
                )
            payload = response.json()
            self._update_model_id(payload)
            hazards: list[dict[str, Any]] = []
            if isinstance(payload, dict) and isinstance(payload.get("hazards"), list):
                for item in payload["hazards"]:
                    if isinstance(item, dict):
                        hazards.append(dict(item))
            return RiskResult(
                hazards=hazards,
                latency_ms=latency,
                status="ok",
                payload=_normalize_payload(payload),
            )
        except httpx.TimeoutException as exc:
            latency = max(0, _now_ms() - started)
            return RiskResult(
                hazards=[],
                latency_ms=latency,
                status="timeout",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__},
            )
        except Exception as exc:  # noqa: BLE001
            latency = max(0, _now_ms() - started)
            return RiskResult(
                hazards=[],
                latency_ms=latency,
                status="error",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__},
            )

    def _update_model_id(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        value = payload.get("model")
        if value is None:
            return
        text = str(value).strip()
        if text:
            self.model_id = text


class HttpSegBackend:
    name = "http"

    def __init__(self, url: str, timeout_ms: int = 1200, model_id: str | None = None) -> None:
        self.url = str(url).strip()
        self.timeout_ms = max(1, int(timeout_ms))
        self.model_id = str(model_id or "").strip() or None
        self.endpoint = _sanitize_endpoint(self.url)

    async def infer(
        self,
        image_bytes: bytes,
        frame_seq: int | None,
        ts_ms: int,
        run_id: str | None = None,
        targets: list[str] | None = None,
    ) -> SegResult:
        started = _now_ms()
        request_payload = {
            "frameSeq": frame_seq,
            "tsMs": ts_ms,
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
        }
        run_id_text = str(run_id or "").strip()
        if run_id_text:
            request_payload["runId"] = run_id_text
        targets_normalized = [str(item).strip() for item in (targets or []) if str(item).strip()]
        if targets_normalized:
            request_payload["targets"] = targets_normalized
        try:
            timeout_s = max(0.05, self.timeout_ms / 1000.0)
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(self.url, json=request_payload)
            latency = max(0, _now_ms() - started)
            if response.status_code >= 400:
                return SegResult(
                    segments=[],
                    latency_ms=latency,
                    status="timeout" if response.status_code == 408 else "error",
                    error=f"http_{response.status_code}",
                    payload={"error": f"http_{response.status_code}", "segmentsCount": 0},
                )
            payload = response.json()
            self._update_model_id(payload)
            segments: list[dict[str, Any]] = []
            if isinstance(payload, dict) and isinstance(payload.get("segments"), list):
                for item in payload["segments"]:
                    if isinstance(item, dict):
                        segments.append(dict(item))
            return SegResult(
                segments=segments,
                latency_ms=latency,
                status="ok",
                payload=_normalize_payload(payload),
            )
        except httpx.TimeoutException as exc:
            latency = max(0, _now_ms() - started)
            return SegResult(
                segments=[],
                latency_ms=latency,
                status="timeout",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__, "segmentsCount": 0},
            )
        except Exception as exc:  # noqa: BLE001
            latency = max(0, _now_ms() - started)
            return SegResult(
                segments=[],
                latency_ms=latency,
                status="error",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__, "segmentsCount": 0},
            )

    def _update_model_id(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        value = payload.get("model")
        if value is None:
            return
        text = str(value).strip()
        if text:
            self.model_id = text


def _normalize_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        out = dict(payload)
        out.pop("latencyMs", None)
        out.pop("latency_ms", None)
        out.pop("durationMs", None)
        out.pop("duration_ms", None)
        return out
    return {"raw": payload}


def _sanitize_endpoint(url: str) -> str | None:
    parsed = urlparse(str(url).strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))


def _collect_risk_threshold_overrides_from_env() -> dict[str, float]:
    env_map = {
        "BYES_RISK_DEPTH_OBS_WARN": "depthObsWarn",
        "BYES_RISK_DEPTH_OBS_CRIT": "depthObsCrit",
        "BYES_RISK_DEPTH_DROPOFF_DELTA": "depthDropoffDelta",
        "BYES_RISK_OBS_WARN": "obsWarn",
        "BYES_RISK_OBS_CRIT": "obsCrit",
        "BYES_RISK_DROPOFF_PEAK": "dropoffPeak",
        "BYES_RISK_DROPOFF_CONTRAST": "dropoffContrast",
        "BYES_RISK_GUARDRAIL_DROPOFF_DELTA": "guardrailDropoffDelta",
        "BYES_RISK_GUARDRAIL_OBS_P10_CRIT": "guardrailObstacleP10Crit",
    }
    out: dict[str, float] = {}
    for env_name, payload_name in env_map.items():
        raw = str(os.getenv(env_name, "")).strip()
        if not raw:
            continue
        try:
            out[payload_name] = float(raw)
        except Exception:  # noqa: BLE001
            continue
    return out
