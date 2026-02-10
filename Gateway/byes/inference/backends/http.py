from __future__ import annotations

import base64
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from byes.inference.backends.base import OCRResult, RiskResult


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
