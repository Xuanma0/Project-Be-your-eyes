from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any

from PIL import Image, UnidentifiedImageError

from byes.config import GatewayConfig


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class FrameArtifacts:
    seq: int
    full_bytes: bytes
    det_jpeg_bytes: bytes
    ocr_jpeg_bytes: bytes
    depth_jpeg_bytes: bytes
    decode_error: bool
    build_latency_ms: int


class FramePreprocessor:
    """Builds reusable frame artifacts for downstream tools per frame seq."""

    def __init__(self, config: GatewayConfig) -> None:
        self._det_max_side = max(1, int(config.det_max_side))
        self._ocr_max_side = max(1, int(config.ocr_max_side))
        self._depth_max_side = max(1, int(config.depth_max_side))
        self._det_quality = self._normalize_quality(config.det_jpeg_quality)
        self._ocr_quality = self._normalize_quality(config.ocr_jpeg_quality)
        self._depth_quality = self._normalize_quality(config.depth_jpeg_quality)

    def build(self, *, seq: int, frame_bytes: bytes, frame_meta: Any | None = None) -> FrameArtifacts:
        _ = frame_meta
        started_ms = _now_ms()
        if not frame_bytes:
            elapsed_ms = max(0, _now_ms() - started_ms)
            return FrameArtifacts(
                seq=seq,
                full_bytes=b"",
                det_jpeg_bytes=b"",
                ocr_jpeg_bytes=b"",
                depth_jpeg_bytes=b"",
                decode_error=True,
                build_latency_ms=elapsed_ms,
            )

        image = self._decode_image(frame_bytes)
        if image is None:
            elapsed_ms = max(0, _now_ms() - started_ms)
            return FrameArtifacts(
                seq=seq,
                full_bytes=frame_bytes,
                det_jpeg_bytes=frame_bytes,
                ocr_jpeg_bytes=frame_bytes,
                depth_jpeg_bytes=frame_bytes,
                decode_error=True,
                build_latency_ms=elapsed_ms,
            )

        det_bytes = self._encode_variant(image, max_side=self._det_max_side, quality=self._det_quality)
        ocr_bytes = self._encode_variant(image, max_side=self._ocr_max_side, quality=self._ocr_quality)
        if self._depth_max_side == self._det_max_side and self._depth_quality == self._det_quality:
            depth_bytes = det_bytes
        else:
            depth_bytes = self._encode_variant(image, max_side=self._depth_max_side, quality=self._depth_quality)

        elapsed_ms = max(0, _now_ms() - started_ms)
        return FrameArtifacts(
            seq=seq,
            full_bytes=frame_bytes,
            det_jpeg_bytes=det_bytes,
            ocr_jpeg_bytes=ocr_bytes,
            depth_jpeg_bytes=depth_bytes,
            decode_error=False,
            build_latency_ms=elapsed_ms,
        )

    @staticmethod
    def _decode_image(frame_bytes: bytes) -> Image.Image | None:
        try:
            with Image.open(io.BytesIO(frame_bytes)) as raw:
                rgb = raw.convert("RGB")
                rgb.load()
            return rgb
        except (UnidentifiedImageError, OSError, ValueError):
            return None

    def _encode_variant(self, image: Image.Image, *, max_side: int, quality: int) -> bytes:
        src = image
        width, height = src.size
        largest = max(width, height)
        if largest > max_side > 0:
            ratio = max_side / float(largest)
            target = (
                max(1, int(round(width * ratio))),
                max(1, int(round(height * ratio))),
            )
            src = src.resize(target, self._resample_filter())

        out = io.BytesIO()
        src.save(out, format="JPEG", quality=quality, optimize=False)
        return out.getvalue()

    @staticmethod
    def _normalize_quality(value: int) -> int:
        return max(30, min(95, int(value)))

    @staticmethod
    def _resample_filter() -> int:
        resampling = getattr(Image, "Resampling", None)
        if resampling is not None:
            return int(resampling.BILINEAR)
        return int(Image.BILINEAR)
