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


class HttpOcrProvider:
    name = "http"

    def __init__(self, endpoint: str, model_id: str | None = None, timeout_ms: int = 1200) -> None:
        endpoint_text = str(endpoint or "").strip()
        if not endpoint_text:
            raise RuntimeError("missing BYES_SERVICE_OCR_ENDPOINT; set ocr endpoint URL for http provider")
        self.url = endpoint_text
        self.endpoint = _sanitize_endpoint(endpoint_text)
        self.timeout_ms = max(1, int(timeout_ms))
        self.model = str(model_id or "").strip() or "http-ocr"

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
            raise RuntimeError(f"ocr_http_timeout:{exc.__class__.__name__}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"ocr_http_failed:{exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            raise RuntimeError(f"ocr_http_status_{response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("ocr_http_invalid_json")

        lines_raw = body.get("lines")
        lines: list[dict[str, Any]] = []
        if isinstance(lines_raw, list):
            for item in lines_raw:
                normalized = _normalize_line(item)
                if normalized is not None:
                    lines.append(normalized)
        else:
            fallback_text = str(body.get("text", "")).strip()
            if fallback_text:
                lines = [{"text": fallback_text}]

        model = str(body.get("model", "")).strip() or self.model
        self.model = model
        latency_ms = max(0, _now_ms() - started)
        image_width = _to_positive_int(body.get("imageWidth"))
        image_height = _to_positive_int(body.get("imageHeight"))
        warnings_count = _to_nonnegative_int(body.get("warningsCount"))
        if any(not str(item.get("text", "")).strip() for item in lines):
            warnings_count += 1

        result: dict[str, Any] = {
            "lines": lines,
            "linesCount": len(lines),
            "model": model,
            "latencyMs": latency_ms,
            "backend": str(body.get("backend", self.name)).strip().lower() or self.name,
            "endpoint": _sanitize_endpoint(body.get("endpoint")) or self.endpoint,
        }
        if image_width is not None:
            result["imageWidth"] = image_width
        if image_height is not None:
            result["imageHeight"] = image_height
        if warnings_count > 0:
            result["warningsCount"] = warnings_count
        return result


def _encode_image_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _normalize_line(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        text = raw.strip()
        return {"text": text} if text else None
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    out: dict[str, Any] = {"text": text}
    score = _to_float(raw.get("score"))
    if score is not None:
        out["score"] = max(0.0, min(1.0, score))
    bbox = raw.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        coords: list[float] = []
        for value in bbox:
            parsed = _to_float(value)
            if parsed is None:
                coords = []
                break
            coords.append(parsed)
        if len(coords) == 4:
            out["bbox"] = coords
    return out


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _to_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _to_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    if parsed <= 0:
        return None
    return parsed


def _sanitize_endpoint(url: Any) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))
