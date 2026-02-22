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


class HttpDepthProvider:
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
            raise RuntimeError("missing BYES_SERVICE_DEPTH_ENDPOINT; set depth endpoint URL for http provider")
        self.url = endpoint_text
        self.endpoint = _sanitize_endpoint(endpoint_text)
        self.timeout_ms = max(1, int(timeout_ms))
        self.model = str(model_id or "").strip() or "http-depth"
        downstream_value = str(downstream or "").strip().lower() or "reference"
        if downstream_value not in {"reference", "da3"}:
            downstream_value = "reference"
        self.downstream = downstream_value

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
    ) -> dict[str, Any]:
        started = _now_ms()
        payload: dict[str, Any] = {
            "frameSeq": frame_seq,
            "image_b64": _encode_image_b64(image),
        }
        run_id_text = str(run_id or "").strip()
        if run_id_text:
            payload["runId"] = run_id_text
        targets_used = [str(item).strip() for item in (targets or []) if str(item).strip()]
        if targets_used:
            payload["targets"] = targets_used

        try:
            timeout_s = max(0.05, self.timeout_ms / 1000.0)
            with httpx.Client(timeout=timeout_s) as client:
                response = client.post(self.url, json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"depth_http_timeout:{exc.__class__.__name__}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"depth_http_failed:{exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            raise RuntimeError(f"depth_http_status_{response.status_code}")

        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("depth_http_invalid_json")

        model = str(body.get("model", "")).strip() or self.model
        self.model = model
        grid = _normalize_grid(body.get("grid"))
        latency_ms = max(0, _now_ms() - started)
        out: dict[str, Any] = {
            "backend": str(body.get("backend", self.name)).strip().lower() or self.name,
            "model": model,
            "endpoint": body.get("endpoint", self.endpoint),
            "latencyMs": latency_ms,
            "warningsCount": int(body.get("warningsCount", 0) or 0),
            "downstream": self.downstream,
        }
        if isinstance(grid, dict):
            out["grid"] = grid
            out["valuesCount"] = len(grid.get("values", []))
            out["gridCount"] = 1
        else:
            out["gridCount"] = 0
        image_width = _to_positive_int(body.get("imageWidth"))
        image_height = _to_positive_int(body.get("imageHeight"))
        if image_width is not None:
            out["imageWidth"] = image_width
        if image_height is not None:
            out["imageHeight"] = image_height
        return out


def _encode_image_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _sanitize_endpoint(url: str) -> str | None:
    parsed = urlparse(str(url).strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))


def _to_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _normalize_grid(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    fmt = str(raw.get("format", "")).strip()
    if fmt != "grid_u16_mm_v1":
        return None
    unit = str(raw.get("unit", "")).strip().lower()
    if unit != "mm":
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
    for value in values_raw:
        try:
            parsed = int(value)
        except Exception:
            return None
        values.append(max(0, min(65535, parsed)))
    if len(values) != gw * gh:
        return None
    return {
        "format": "grid_u16_mm_v1",
        "size": [gw, gh],
        "unit": "mm",
        "values": values,
    }
