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


class HttpSegProvider:
    name = "http"

    def __init__(
        self,
        endpoint: str,
        model_id: str | None = None,
        timeout_ms: int = 1200,
        downstream: str | None = None,
    ) -> None:
        endpoint_text = str(endpoint or "").strip()
        if not endpoint_text:
            raise RuntimeError("missing BYES_SERVICE_SEG_ENDPOINT; set seg endpoint URL for http provider")
        self.url = endpoint_text
        self.endpoint = _sanitize_endpoint(endpoint_text)
        self.timeout_ms = max(1, int(timeout_ms))
        self.model = str(model_id or "").strip() or "http-seg"
        downstream_value = str(downstream or "").strip().lower() or "reference"
        if downstream_value not in {"reference", "sam3"}:
            downstream_value = "reference"
        self.downstream = downstream_value

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = _now_ms()
        payload = {
            "frameSeq": frame_seq,
            "image_b64": _encode_image_b64(image),
        }
        run_id_text = str(run_id or "").strip()
        if run_id_text:
            payload["runId"] = run_id_text
        targets_used = [str(item).strip() for item in (targets or []) if str(item).strip()]
        if targets_used:
            payload["targets"] = targets_used
        if isinstance(prompt, dict):
            payload["prompt"] = prompt
        try:
            timeout_s = max(0.05, self.timeout_ms / 1000.0)
            with httpx.Client(timeout=timeout_s) as client:
                response = client.post(self.url, json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"seg_http_timeout:{exc.__class__.__name__}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"seg_http_failed:{exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            raise RuntimeError(f"seg_http_status_{response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("seg_http_invalid_json")

        segments: list[dict[str, Any]] = []
        raw_segments = body.get("segments")
        if isinstance(raw_segments, list):
            for item in raw_segments:
                normalized = _normalize_segment(item)
                if normalized is not None:
                    segments.append(normalized)

        model = str(body.get("model", "")).strip() or self.model
        self.model = model
        latency_ms = max(0, _now_ms() - started)
        return {
            "segments": segments,
            "model": model,
            "latencyMs": latency_ms,
            "backend": self.name,
            "endpoint": self.endpoint,
            "targetsCount": int(body.get("targetsCount", len(targets_used)) or 0),
            "targetsUsed": body.get("targetsUsed", targets_used),
            "downstream": self.downstream,
        }


def _encode_image_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _normalize_segment(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    label = str(item.get("label", "")).strip()
    if not label:
        label = "unknown"
    try:
        score = float(item.get("score", 0.0))
    except Exception:  # noqa: BLE001
        score = 0.0
    bbox = item.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    normalized_bbox: list[float] = []
    for value in bbox:
        try:
            normalized_bbox.append(float(value))
        except Exception:  # noqa: BLE001
            return None
    out: dict[str, Any] = {"label": label, "score": score, "bbox": normalized_bbox}
    mask = _normalize_mask(item.get("mask"))
    if isinstance(mask, dict):
        out["mask"] = mask
    return out


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


def _sanitize_endpoint(url: str) -> str | None:
    parsed = urlparse(str(url).strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))
