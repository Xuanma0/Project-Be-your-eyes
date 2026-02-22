from __future__ import annotations

import base64
import os
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from byes.inference.backends.base import OCRResult, RiskResult, SegResult, DepthResult, SlamResult


def _now_ms() -> int:
    return int(time.time() * 1000)


class HttpOCRBackend:
    name = "http"

    def __init__(self, url: str, timeout_ms: int = 1500, model_id: str | None = None) -> None:
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
        prompt: dict[str, Any] | None = None,
    ) -> OCRResult:
        started = _now_ms()
        request_payload: dict[str, Any] = {
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
        if isinstance(prompt, dict):
            request_payload["prompt"] = prompt
        try:
            timeout_s = max(0.05, self.timeout_ms / 1000.0)
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(self.url, json=request_payload)
            latency = max(0, _now_ms() - started)
            if response.status_code >= 400:
                return OCRResult(
                    text="",
                    lines=[],
                    latency_ms=latency,
                    status="timeout" if response.status_code == 408 else "error",
                    error=f"http_{response.status_code}",
                    payload={"error": f"http_{response.status_code}"},
                )
            payload = response.json()
            self._update_model_id(payload)
            lines: list[dict[str, Any]] = []
            text = ""
            if isinstance(payload, dict):
                raw_lines = payload.get("lines")
                if isinstance(raw_lines, list):
                    for row in raw_lines:
                        normalized = _normalize_ocr_line(row)
                        if normalized is not None:
                            lines.append(normalized)
                text = str(payload.get("text", payload.get("summary", "")) or "").strip()
            if not lines and text:
                lines = [{"text": text}]
            if not text and lines:
                text = " ".join(str(item.get("text", "")).strip() for item in lines if str(item.get("text", "")).strip())
            return OCRResult(
                text=text,
                lines=lines,
                latency_ms=latency,
                status="ok",
                payload=_normalize_payload(payload),
                error=None,
            )
        except httpx.TimeoutException as exc:
            latency = max(0, _now_ms() - started)
            return OCRResult(
                text="",
                lines=[],
                latency_ms=latency,
                status="timeout",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__},
            )
        except Exception as exc:  # noqa: BLE001
            latency = max(0, _now_ms() - started)
            return OCRResult(
                text="",
                lines=[],
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
        prompt: dict[str, Any] | None = None,
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
        if isinstance(prompt, dict):
            request_payload["prompt"] = prompt
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


class HttpDepthBackend:
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
    ) -> DepthResult:
        started = _now_ms()
        request_payload: dict[str, Any] = {
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
                return DepthResult(
                    grid=None,
                    latency_ms=latency,
                    status="timeout" if response.status_code == 408 else "error",
                    error=f"http_{response.status_code}",
                    payload={"error": f"http_{response.status_code}", "gridCount": 0, "valuesCount": 0},
                )
            payload = response.json()
            self._update_model_id(payload)
            normalized_payload = _normalize_payload(payload)
            grid = None
            if isinstance(payload, dict):
                grid = _normalize_depth_grid(payload.get("grid"))
            if isinstance(grid, dict):
                normalized_payload["grid"] = grid
                normalized_payload["gridCount"] = 1
                normalized_payload["valuesCount"] = len(grid.get("values", []))
            else:
                normalized_payload.setdefault("gridCount", 0)
                normalized_payload.setdefault("valuesCount", 0)
            return DepthResult(
                grid=grid,
                latency_ms=latency,
                status="ok",
                payload=normalized_payload,
            )
        except httpx.TimeoutException as exc:
            latency = max(0, _now_ms() - started)
            return DepthResult(
                grid=None,
                latency_ms=latency,
                status="timeout",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__, "gridCount": 0, "valuesCount": 0},
            )
        except Exception as exc:  # noqa: BLE001
            latency = max(0, _now_ms() - started)
            return DepthResult(
                grid=None,
                latency_ms=latency,
                status="error",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__, "gridCount": 0, "valuesCount": 0},
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


class HttpSlamBackend:
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
        prompt: dict[str, Any] | None = None,
    ) -> SlamResult:
        started = _now_ms()
        request_payload: dict[str, Any] = {
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
        if isinstance(prompt, dict):
            request_payload["prompt"] = prompt
        try:
            timeout_s = max(0.05, self.timeout_ms / 1000.0)
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(self.url, json=request_payload)
            latency = max(0, _now_ms() - started)
            if response.status_code >= 400:
                return SlamResult(
                    tracking_state="unknown",
                    pose={},
                    latency_ms=latency,
                    status="timeout" if response.status_code == 408 else "error",
                    error=f"http_{response.status_code}",
                    payload={"error": f"http_{response.status_code}"},
                )
            payload = response.json()
            self._update_model_id(payload)
            tracking_state = _normalize_tracking_state(payload.get("trackingState") if isinstance(payload, dict) else None)
            pose = _normalize_pose(payload.get("pose") if isinstance(payload, dict) else None)
            return SlamResult(
                tracking_state=tracking_state,
                pose=pose,
                latency_ms=latency,
                status="ok",
                payload=_normalize_payload(payload),
            )
        except httpx.TimeoutException as exc:
            latency = max(0, _now_ms() - started)
            return SlamResult(
                tracking_state="unknown",
                pose={},
                latency_ms=latency,
                status="timeout",
                error=exc.__class__.__name__,
                payload={"error": exc.__class__.__name__},
            )
        except Exception as exc:  # noqa: BLE001
            latency = max(0, _now_ms() - started)
            return SlamResult(
                tracking_state="unknown",
                pose={},
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


def _normalize_ocr_line(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        text = raw.strip()
        return {"text": text} if text else None
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    out: dict[str, Any] = {"text": text}
    score = raw.get("score")
    if score is not None:
        try:
            parsed = float(score)
            out["score"] = max(0.0, min(1.0, parsed))
        except Exception:
            pass
    bbox = raw.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        coords: list[float] = []
        for value in bbox:
            try:
                coords.append(float(value))
            except Exception:
                coords = []
                break
        if len(coords) == 4:
            out["bbox"] = coords
    return out


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


def _normalize_depth_grid(raw: Any) -> dict[str, Any] | None:
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


def _normalize_tracking_state(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"tracking", "lost", "relocalized", "initializing"}:
        return value
    return "unknown"


def _normalize_pose(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    t_raw = raw.get("t")
    q_raw = raw.get("q")
    if not isinstance(t_raw, list) or len(t_raw) != 3:
        return {}
    if not isinstance(q_raw, list) or len(q_raw) != 4:
        return {}
    try:
        t = [float(t_raw[0]), float(t_raw[1]), float(t_raw[2])]
        q = [float(q_raw[0]), float(q_raw[1]), float(q_raw[2]), float(q_raw[3])]
    except Exception:
        return {}
    out: dict[str, Any] = {"t": t, "q": q}
    frame = str(raw.get("frame", "")).strip().lower()
    if frame in {"world_to_cam", "cam_to_world"}:
        out["frame"] = frame
    map_id = raw.get("mapId")
    map_id_text = str(map_id).strip() if map_id is not None else ""
    if map_id_text:
        out["mapId"] = map_id_text
    cov = raw.get("cov")
    if isinstance(cov, dict):
        out["cov"] = cov
    return out
