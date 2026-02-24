from __future__ import annotations

import base64
import io
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from PIL import Image


def _now_ms() -> int:
    return int(time.time() * 1000)


class HttpSlamProvider:
    name = "http"

    def __init__(self, endpoint: str, model_id: str | None = None, timeout_ms: int = 1200) -> None:
        endpoint_text = str(endpoint or "").strip()
        if not endpoint_text:
            raise RuntimeError("missing BYES_SERVICE_SLAM_ENDPOINT; set slam endpoint URL for http provider")
        self.url = endpoint_text
        self.endpoint = _sanitize_endpoint(endpoint_text)
        self.timeout_ms = max(1, int(timeout_ms))
        self.model = str(model_id or "").strip() or "http-slam"

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = _now_ms()
        payload: dict[str, Any] = {
            "frameSeq": frame_seq,
            "image_b64": _encode_image_b64(image),
        }
        run_id_text = str(run_id or "").strip()
        if run_id_text:
            payload["runId"] = run_id_text
        targets_list = [str(item).strip() for item in (targets or []) if str(item).strip()]
        if targets_list:
            payload["targets"] = targets_list
        if isinstance(prompt, dict):
            payload["prompt"] = prompt

        try:
            timeout_s = max(0.05, self.timeout_ms / 1000.0)
            with httpx.Client(timeout=timeout_s) as client:
                response = client.post(self.url, json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"slam_http_timeout:{exc.__class__.__name__}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"slam_http_failed:{exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            raise RuntimeError(f"slam_http_status_{response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("slam_http_invalid_json")

        model = str(body.get("model", "")).strip() or self.model
        self.model = model
        pose = _normalize_pose(body.get("pose"))
        tracking_state = _normalize_tracking_state(body.get("trackingState"))
        if pose is None or not tracking_state:
            raise RuntimeError("slam_http_invalid_payload")
        latency_ms = max(0, _now_ms() - started)
        out: dict[str, Any] = {
            "schemaVersion": "byes.slam_pose.v1",
            "trackingState": tracking_state,
            "pose": pose,
            "model": model,
            "backend": str(body.get("backend", self.name)).strip().lower() or self.name,
            "endpoint": _sanitize_endpoint(body.get("endpoint")) or self.endpoint,
            "latencyMs": latency_ms,
        }
        map_id = body.get("mapId")
        map_id_text = str(map_id).strip() if map_id is not None else ""
        if map_id_text:
            out["mapId"] = map_id_text
        warnings_count = _to_nonnegative_int(body.get("warningsCount"))
        if warnings_count > 0:
            out["warningsCount"] = warnings_count
        cov = body.get("cov")
        if isinstance(cov, dict):
            out["cov"] = cov
        return out


def _encode_image_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _normalize_pose(raw: Any) -> dict[str, Any] | None:
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
    frame = str(raw.get("frame", "")).strip()
    if frame:
        out["frame"] = frame
    map_id = raw.get("mapId")
    map_id_text = str(map_id).strip() if map_id is not None else ""
    if map_id_text:
        out["mapId"] = map_id_text
    return out


def _normalize_tracking_state(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"tracking", "lost", "relocalized", "initializing"}:
        return value
    if value:
        return "unknown"
    return ""


def _sanitize_endpoint(url: Any) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))


def _to_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0
