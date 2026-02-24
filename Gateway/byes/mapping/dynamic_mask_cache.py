from __future__ import annotations

import math
from typing import Any


class DynamicMaskCache:
    """Run-scoped temporal cache for dynamic segmentation masks keyed by trackId."""

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, dict[str, Any]]] = {}

    def reset(self, run_id: str | None = None) -> None:
        if run_id is None:
            self._runs.clear()
            return
        key = str(run_id or "").strip()
        if not key:
            return
        self._runs.pop(key, None)

    def update_from_segments(
        self,
        *,
        run_id: str,
        frame_seq: int,
        segments: list[dict[str, Any]] | None,
        dynamic_labels_set: set[str] | None = None,
        image_w: int | None = None,
        image_h: int | None = None,
    ) -> int:
        run_key = str(run_id or "").strip()
        if not run_key:
            return 0
        rows = segments if isinstance(segments, list) else []
        dynamic_labels = {str(item).strip().lower() for item in (dynamic_labels_set or set()) if str(item).strip()}
        frame = max(1, int(frame_seq))
        cache = self._runs.setdefault(run_key, {})
        updated = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            track_id = str(row.get("trackId", "")).strip()
            if not track_id:
                continue
            label = str(row.get("label", "")).strip().lower()
            if dynamic_labels and label not in dynamic_labels:
                continue
            entry: dict[str, Any] = {
                "trackId": track_id,
                "label": label,
                "lastSeenFrameSeq": frame,
            }
            mask = _decode_rle_mask(row.get("mask"))
            if mask is not None:
                entry["mask"] = mask
            else:
                bbox = _parse_bbox(row.get("bbox"))
                if bbox is not None:
                    entry["bbox"] = bbox
                    entry["imageW"] = int(max(1, int(image_w or 1)))
                    entry["imageH"] = int(max(1, int(image_h or 1)))
            if "mask" not in entry and "bbox" not in entry:
                continue
            cache[track_id] = entry
            updated += 1
        return updated

    def build_union_mask(
        self,
        *,
        run_id: str,
        image_w: int,
        image_h: int,
        now_frame_seq: int,
        ttl_frames: int,
    ) -> tuple[list[bool], int, bool]:
        w = max(1, int(image_w))
        h = max(1, int(image_h))
        run_key = str(run_id or "").strip()
        if not run_key:
            return ([False] * (w * h), 0, False)
        cache = self._runs.get(run_key)
        if not isinstance(cache, dict) or not cache:
            return ([False] * (w * h), 0, False)
        ttl = max(0, int(ttl_frames))
        frame = max(1, int(now_frame_seq))
        union = [False] * (w * h)
        tracks_used = 0
        cache_hit = False
        stale_ids: list[str] = []
        for track_id, row in cache.items():
            if not isinstance(row, dict):
                continue
            last_seen = int(max(1, int(row.get("lastSeenFrameSeq", frame))))
            age = frame - last_seen
            if age < 0:
                age = 0
            if age > ttl:
                stale_ids.append(track_id)
                continue
            contributed = False
            mask = row.get("mask")
            if isinstance(mask, dict):
                contributed = _overlay_mask(union, target_w=w, target_h=h, source=mask)
            if not contributed:
                bbox = _parse_bbox(row.get("bbox"))
                if bbox is not None:
                    src_w = int(max(1, int(row.get("imageW", w))))
                    src_h = int(max(1, int(row.get("imageH", h))))
                    contributed = _overlay_bbox(union, target_w=w, target_h=h, bbox=bbox, source_w=src_w, source_h=src_h)
            if contributed:
                tracks_used += 1
                cache_hit = True
        for track_id in stale_ids:
            cache.pop(track_id, None)
        return union, int(tracks_used), bool(cache_hit)


def _decode_rle_mask(mask: Any) -> dict[str, Any] | None:
    if not isinstance(mask, dict):
        return None
    if str(mask.get("format", "")).strip() != "rle_v1":
        return None
    size = mask.get("size")
    if not isinstance(size, list) or len(size) != 2:
        return None
    h = _to_positive_int(size[0])
    w = _to_positive_int(size[1])
    if h <= 0 or w <= 0:
        return None
    counts = mask.get("counts")
    if not isinstance(counts, list):
        return None
    total = h * w
    out = [False] * total
    cursor = 0
    value = 0
    for row in counts:
        try:
            run = int(row)
        except Exception:
            return None
        if run < 0:
            return None
        end = cursor + run
        if end > total:
            return None
        if value == 1:
            for idx in range(cursor, end):
                out[idx] = True
        cursor = end
        value = 1 - value
    if cursor != total:
        return None
    return {"w": w, "h": h, "values": out}


def _parse_bbox(raw: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    parsed: list[float] = []
    for item in raw:
        try:
            parsed.append(float(item))
        except Exception:
            return None
    x0, y0, x1, y1 = parsed
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return x0, y0, x1, y1


def _overlay_mask(target: list[bool], *, target_w: int, target_h: int, source: dict[str, Any]) -> bool:
    src_w = _to_positive_int(source.get("w"))
    src_h = _to_positive_int(source.get("h"))
    values = source.get("values")
    if src_w <= 0 or src_h <= 0 or not isinstance(values, list) or len(values) != src_w * src_h:
        return False
    touched = False
    if src_w == target_w and src_h == target_h:
        for idx, flag in enumerate(values):
            if bool(flag):
                target[idx] = True
                touched = True
        return touched
    for sy in range(src_h):
        ty = min(target_h - 1, max(0, int((float(sy) / float(max(1, src_h))) * float(target_h))))
        row_base = sy * src_w
        out_base = ty * target_w
        for sx in range(src_w):
            if not bool(values[row_base + sx]):
                continue
            tx = min(target_w - 1, max(0, int((float(sx) / float(max(1, src_w))) * float(target_w))))
            target[out_base + tx] = True
            touched = True
    return touched


def _overlay_bbox(
    target: list[bool],
    *,
    target_w: int,
    target_h: int,
    bbox: tuple[float, float, float, float],
    source_w: int,
    source_h: int,
) -> bool:
    x0, y0, x1, y1 = bbox
    sx0 = int(math.floor((x0 / float(max(1, source_w))) * float(target_w)))
    sx1 = int(math.ceil((x1 / float(max(1, source_w))) * float(target_w)))
    sy0 = int(math.floor((y0 / float(max(1, source_h))) * float(target_h)))
    sy1 = int(math.ceil((y1 / float(max(1, source_h))) * float(target_h)))
    gx0 = max(0, min(target_w - 1, sx0))
    gx1 = max(0, min(target_w, sx1))
    gy0 = max(0, min(target_h - 1, sy0))
    gy1 = max(0, min(target_h, sy1))
    touched = False
    for gy in range(gy0, max(gy0, gy1)):
        row_base = gy * target_w
        for gx in range(gx0, max(gx0, gx1)):
            target[row_base + gx] = True
            touched = True
    return touched


def _to_positive_int(value: Any) -> int:
    try:
        if value is None or isinstance(value, bool):
            return 0
        return max(0, int(float(value)))
    except Exception:
        return 0
