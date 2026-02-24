from __future__ import annotations

import base64
import math
from typing import Any, Iterable


DEFAULT_COSTMAP_CONFIG = {
    "gridH": 32,
    "gridW": 32,
    "resolutionM": 0.1,
    "depthThreshM": 1.0,
    "dynamicLabels": ("person", "car"),
    "enableDynamicTrack": False,
    "dynamicTrackTtlFrames": 5,
}

DEFAULT_COSTMAP_CONTEXT_BUDGET = {
    "maxChars": 512,
    "mode": "topk_hotspots",
}
DEFAULT_COSTMAP_CONTEXT_SOURCE = "auto"

_ALLOWED_CONTEXT_MODES = {"topk_hotspots"}
_ALLOWED_CONTEXT_SOURCES = {"auto", "raw", "fused"}


def build_local_costmap(
    *,
    run_id: str,
    frame_seq: int,
    depth_payload: dict[str, Any] | None,
    seg_payload: dict[str, Any] | None,
    slam_payload: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
    dynamic_mask_cache: Any | None = None,
    backend: str | None = "local",
    model: str | None = "local-costmap-v1",
    endpoint: str | None = None,
) -> dict[str, Any]:
    normalized_cfg = _normalize_costmap_config(config)
    cost_h = int(normalized_cfg["gridH"])
    cost_w = int(normalized_cfg["gridW"])
    depth_thresh_m = float(normalized_cfg["depthThreshM"])
    dynamic_labels = {str(item).strip().lower() for item in normalized_cfg["dynamicLabels"] if str(item).strip()}
    enable_dynamic_track = bool(normalized_cfg["enableDynamicTrack"])
    dynamic_track_ttl_frames = int(max(0, int(normalized_cfg["dynamicTrackTtlFrames"])))

    grid_values = [0] * (cost_h * cost_w)
    warnings_count = 0

    depth_grid = _normalize_depth_grid(depth_payload)
    has_depth = isinstance(depth_grid, dict)
    has_seg = isinstance(seg_payload, dict) and isinstance(seg_payload.get("segments"), list) and len(seg_payload.get("segments")) > 0
    has_slam = isinstance(slam_payload, dict) and bool(slam_payload)

    filtered_count = 0
    considered_count = 0
    dynamic_temporal_used = False
    dynamic_tracks_used = 0
    dynamic_mask_used = False
    if not has_depth:
        warnings_count += 1
    else:
        gw = int(depth_grid["w"])
        gh = int(depth_grid["h"])
        depth_values = depth_grid["values"]
        roi_start = int(max(0, (gh * 2) // 3))
        dynamic_mask, dynamic_warnings = _build_dynamic_mask(
            seg_payload=seg_payload,
            depth_w=gw,
            depth_h=gh,
            dynamic_labels=dynamic_labels,
        )
        warnings_count += int(dynamic_warnings)
        current_has_dynamic_mask = any(dynamic_mask)
        track_ids_present = _has_dynamic_track_ids(seg_payload=seg_payload, dynamic_labels=dynamic_labels)

        if enable_dynamic_track and dynamic_mask_cache is not None:
            segments = seg_payload.get("segments") if isinstance(seg_payload, dict) else []
            if isinstance(segments, list):
                image_w = _to_nonnegative_int((seg_payload or {}).get("imageWidth"), gw) or gw
                image_h = _to_nonnegative_int((seg_payload or {}).get("imageHeight"), gh) or gh
                try:
                    dynamic_mask_cache.update_from_segments(
                        run_id=str(run_id or "").strip() or "costmap-run",
                        frame_seq=int(max(1, int(frame_seq))),
                        segments=[row for row in segments if isinstance(row, dict)],
                        dynamic_labels_set=dynamic_labels,
                        image_w=image_w,
                        image_h=image_h,
                    )
                    cached_mask, tracks_used, cache_hit = dynamic_mask_cache.build_union_mask(
                        run_id=str(run_id or "").strip() or "costmap-run",
                        image_w=gw,
                        image_h=gh,
                        now_frame_seq=int(max(1, int(frame_seq))),
                        ttl_frames=dynamic_track_ttl_frames,
                    )
                    if isinstance(cached_mask, list) and len(cached_mask) == len(dynamic_mask):
                        for idx, flag in enumerate(cached_mask):
                            if bool(flag):
                                dynamic_mask[idx] = True
                    dynamic_tracks_used = int(max(0, tracks_used))
                    dynamic_temporal_used = bool(track_ids_present or cache_hit)
                    dynamic_mask_used = bool(cache_hit and not current_has_dynamic_mask)
                except Exception:
                    warnings_count += 1

        for y in range(roi_start, gh):
            for x in range(gw):
                idx = y * gw + x
                depth_mm = int(depth_values[idx])
                if depth_mm <= 0:
                    continue
                considered_count += 1
                if dynamic_mask[idx]:
                    filtered_count += 1
                    continue
                depth_m = float(depth_mm) / 1000.0
                if depth_m > depth_thresh_m:
                    continue
                col = min(cost_w - 1, max(0, int((float(x) / max(1.0, float(gw))) * float(cost_w))))
                near_ratio = 1.0 - min(1.0, max(0.0, depth_m / max(0.001, depth_thresh_m)))
                row = min(cost_h - 1, max(0, int(near_ratio * float(cost_h - 1))))
                grid_values[row * cost_w + col] = 255

        grid_values = _dilate_u8_grid(grid_values, cost_w, cost_h)

    occupied_cells = sum(1 for value in grid_values if int(value) > 0)
    mean_cost = float(sum(grid_values)) / float(max(1, len(grid_values)))
    max_cost = max(grid_values) if grid_values else 0
    dynamic_filtered_rate = float(filtered_count) / float(max(1, considered_count))

    return {
        "schemaVersion": "byes.costmap.v1",
        "runId": str(run_id or "").strip() or "costmap-run",
        "frameSeq": int(max(1, int(frame_seq))),
        "frame": "local",
        "grid": {
            "format": "grid_u8_cost_v1",
            "size": [int(cost_h), int(cost_w)],
            "resolutionM": float(max(0.001, float(normalized_cfg["resolutionM"]))),
            "origin": {"x": 0.0, "y": 0.0},
            "dataB64": base64.b64encode(bytes(grid_values)).decode("ascii"),
        },
        "stats": {
            "occupiedCells": int(occupied_cells),
            "meanCost": float(round(mean_cost, 6)),
            "maxCost": int(max_cost),
            "dynamicFilteredRate": float(round(max(0.0, min(1.0, dynamic_filtered_rate)), 6)),
            "dynamicTemporalUsed": bool(dynamic_temporal_used),
            "dynamicTracksUsed": int(max(0, dynamic_tracks_used)),
            "dynamicTtlFrames": int(max(0, dynamic_track_ttl_frames)),
            "dynamicMaskUsed": bool(dynamic_mask_used),
            "sources": {
                "depth": bool(has_depth),
                "seg": bool(has_seg),
                "slam": bool(has_slam),
            },
        },
        "backend": str(backend).strip() if backend is not None else None,
        "model": str(model).strip() if model is not None else None,
        "endpoint": str(endpoint).strip() if endpoint else None,
        "warningsCount": int(max(0, warnings_count)),
    }


def build_costmap_context_pack(
    *,
    costmap_payload: dict[str, Any] | None,
    budget: dict[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    payload = costmap_payload if isinstance(costmap_payload, dict) else {}
    run_id = str(payload.get("runId", "")).strip() or "costmap-context"
    frame_seq = _to_nonnegative_int(payload.get("frameSeq"), 1)
    normalized_budget = _normalize_context_budget(budget)
    max_chars = int(normalized_budget["maxChars"])
    mode = str(normalized_budget["mode"])

    grid = payload.get("grid")
    grid = grid if isinstance(grid, dict) else {}
    size = grid.get("size")
    size = size if isinstance(size, list) else []
    grid_h = _to_nonnegative_int(size[0], 0) if len(size) > 0 else 0
    grid_w = _to_nonnegative_int(size[1], 0) if len(size) > 1 else 0
    data_b64 = str(grid.get("dataB64", "")).strip()
    cells = _decode_u8_grid(data_b64, grid_h, grid_w)
    hotspots = _extract_hotspots(cells, grid_h, grid_w)

    full_fragment = _render_hotspots_fragment(hotspots)
    in_chars_total = len(full_fragment)
    in_cells = int(max(0, grid_h * grid_w))

    out_lines: list[str] = []
    remaining = max(0, int(max_chars))
    hotspots_kept = 0
    if hotspots:
        prefix = "[COSTMAP] hotspots: "
    else:
        prefix = "[COSTMAP] hotspots: none"
    if len(prefix) <= remaining:
        out_lines.append(prefix)
        remaining -= len(prefix)
    else:
        out_lines.append(prefix[:remaining])
        remaining = 0
    for row in hotspots:
        if remaining <= 0:
            break
        entry = row["line"]
        separator = "; " if out_lines and out_lines[0].startswith("[COSTMAP] hotspots:") and out_lines[0] != "[COSTMAP] hotspots: none" else ""
        text = f"{separator}{entry}"
        if len(text) <= remaining:
            if out_lines:
                out_lines[-1] += text
            else:
                out_lines.append(text)
            remaining -= len(text)
            hotspots_kept += 1
        else:
            break

    prompt_fragment = "".join(out_lines).strip()
    if not prompt_fragment:
        prompt_fragment = "[COSTMAP] hotspots: none"
    out_chars_total = len(prompt_fragment)
    token_approx = _token_approx(out_chars_total)
    chars_dropped = max(0, in_chars_total - out_chars_total)
    hotspots_dropped = max(0, len(hotspots) - hotspots_kept)

    source_text = str(source or "").strip().lower()
    if source_text not in _ALLOWED_CONTEXT_SOURCES:
        source_text = "raw"
    summary = (
        f"source={source_text}; mode={mode}; hotspots={hotspots_kept}/{len(hotspots)}; "
        f"chars={out_chars_total}/{max_chars}; dropped={hotspots_dropped}"
    )
    return {
        "schemaVersion": "costmap.context.v1",
        "runId": run_id,
        "frameSeq": int(max(1, frame_seq)),
        "budget": {
            "maxChars": int(max_chars),
            "mode": mode,
        },
        "stats": {
            "in": {
                "cells": int(in_cells),
                "charsTotal": int(in_chars_total),
            },
            "out": {
                "charsTotal": int(out_chars_total),
                "tokenApprox": int(token_approx),
                "hotspots": int(hotspots_kept),
            },
            "truncation": {
                "hotspotsDropped": int(hotspots_dropped),
                "charsDropped": int(chars_dropped),
            },
        },
        "text": {
            "summary": summary,
            "promptFragment": prompt_fragment,
            "promptFragmentLength": int(len(prompt_fragment)),
        },
    }


def find_latest_costmap_from_events(
    events: Iterable[dict[str, Any]] | None,
    *,
    run_id: str | None = None,
    frame_seq: int | None = None,
    source: str | None = "raw",
) -> dict[str, Any] | None:
    selected: tuple[int, int, dict[str, Any]] | None = None
    wanted_run = str(run_id or "").strip()
    wanted_frame = int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else None
    source_mode = str(source or "raw").strip().lower()
    if source_mode not in _ALLOWED_CONTEXT_SOURCES:
        source_mode = "raw"
    if source_mode == "raw":
        event_names = {"map.costmap"}
        allowed_schema = {"byes.costmap.v1"}
    elif source_mode == "fused":
        event_names = {"map.costmap_fused"}
        allowed_schema = {"byes.costmap_fused.v1"}
    else:
        event_names = {"map.costmap_fused", "map.costmap"}
        allowed_schema = {"byes.costmap_fused.v1", "byes.costmap.v1"}
    prefer_fused = source_mode == "auto"
    selected_kind = ""
    for index, row in enumerate(events or []):
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        event_name = str(event.get("name", "")).strip().lower()
        if event_name not in event_names:
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        event_run = str(event.get("runId", "")).strip()
        if wanted_run and event_run and event_run != wanted_run:
            continue
        event_seq = _to_nonnegative_int(event.get("frameSeq"), 0)
        if wanted_frame is not None and event_seq != wanted_frame:
            continue
        ts = _to_nonnegative_int(event.get("tsMs"), 0)
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        schema_version = str(payload.get("schemaVersion", "")).strip()
        if schema_version not in allowed_schema:
            continue
        marker = (ts, index, payload)
        if selected is None:
            selected = marker
            selected_kind = event_name
            continue
        if prefer_fused:
            if event_name == "map.costmap_fused" and selected_kind != "map.costmap_fused":
                selected = marker
                selected_kind = event_name
                continue
            if event_name != selected_kind:
                continue
        if (ts, index) >= (selected[0], selected[1]):
            selected = marker
            selected_kind = event_name
    if selected is None:
        return None
    return dict(selected[2])


def _normalize_costmap_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    labels_raw = source.get("dynamicLabels", DEFAULT_COSTMAP_CONFIG["dynamicLabels"])
    labels = labels_raw if isinstance(labels_raw, (list, tuple, set)) else str(labels_raw or "").split(",")
    return {
        "gridH": max(4, _to_nonnegative_int(source.get("gridH"), int(DEFAULT_COSTMAP_CONFIG["gridH"]))),
        "gridW": max(4, _to_nonnegative_int(source.get("gridW"), int(DEFAULT_COSTMAP_CONFIG["gridW"]))),
        "resolutionM": max(0.01, _to_float(source.get("resolutionM"), float(DEFAULT_COSTMAP_CONFIG["resolutionM"]))),
        "depthThreshM": max(0.1, _to_float(source.get("depthThreshM"), float(DEFAULT_COSTMAP_CONFIG["depthThreshM"]))),
        "dynamicLabels": [str(item).strip().lower() for item in labels if str(item).strip()],
        "enableDynamicTrack": bool(source.get("enableDynamicTrack", DEFAULT_COSTMAP_CONFIG["enableDynamicTrack"])),
        "dynamicTrackTtlFrames": max(
            0,
            _to_nonnegative_int(
                source.get("dynamicTrackTtlFrames"),
                int(DEFAULT_COSTMAP_CONFIG["dynamicTrackTtlFrames"]),
            ),
        ),
    }


def _normalize_context_budget(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    mode_raw = str(source.get("mode", DEFAULT_COSTMAP_CONTEXT_BUDGET["mode"])).strip().lower()
    mode = mode_raw if mode_raw in _ALLOWED_CONTEXT_MODES else str(DEFAULT_COSTMAP_CONTEXT_BUDGET["mode"])
    return {
        "maxChars": max(0, _to_nonnegative_int(source.get("maxChars"), int(DEFAULT_COSTMAP_CONTEXT_BUDGET["maxChars"]))),
        "mode": mode,
    }


def _normalize_depth_grid(depth_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = depth_payload if isinstance(depth_payload, dict) else {}
    grid = payload.get("grid")
    if not isinstance(grid, dict):
        return None
    if str(grid.get("format", "")).strip() != "grid_u16_mm_v1":
        return None
    size = grid.get("size")
    if not isinstance(size, list) or len(size) != 2:
        return None
    w = _to_nonnegative_int(size[0], 0)
    h = _to_nonnegative_int(size[1], 0)
    if w <= 0 or h <= 0:
        return None
    values_raw = grid.get("values")
    if not isinstance(values_raw, list):
        return None
    values: list[int] = []
    for value in values_raw:
        try:
            parsed = int(value)
        except Exception:
            return None
        values.append(max(0, min(65535, parsed)))
    if len(values) != w * h:
        return None
    return {"w": w, "h": h, "values": values}


def _build_dynamic_mask(
    *,
    seg_payload: dict[str, Any] | None,
    depth_w: int,
    depth_h: int,
    dynamic_labels: set[str],
) -> tuple[list[bool], int]:
    mask = [False] * (depth_w * depth_h)
    warnings = 0
    payload = seg_payload if isinstance(seg_payload, dict) else {}
    segments = payload.get("segments")
    segments = segments if isinstance(segments, list) else []
    image_w = _to_nonnegative_int(payload.get("imageWidth"), depth_w) or depth_w
    image_h = _to_nonnegative_int(payload.get("imageHeight"), depth_h) or depth_h

    for row in segments:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label", "")).strip().lower()
        if not label or label not in dynamic_labels:
            continue
        seg_mask = row.get("mask")
        decoded = _decode_seg_mask(seg_mask, depth_w=depth_w, depth_h=depth_h)
        if decoded is not None:
            for idx, value in enumerate(decoded):
                if value:
                    mask[idx] = True
            continue
        if seg_mask is not None:
            warnings += 1
        bbox = row.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        parsed_bbox: list[float] = []
        valid = True
        for value in bbox:
            parsed = _try_float(value)
            if parsed is None:
                valid = False
                break
            parsed_bbox.append(parsed)
        if not valid:
            continue
        x0, y0, x1, y1 = parsed_bbox
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        gx0 = max(0, min(depth_w - 1, int(math.floor((x0 / max(1.0, float(image_w))) * float(depth_w)))))
        gx1 = max(0, min(depth_w, int(math.ceil((x1 / max(1.0, float(image_w))) * float(depth_w)))))
        gy0 = max(0, min(depth_h - 1, int(math.floor((y0 / max(1.0, float(image_h))) * float(depth_h)))))
        gy1 = max(0, min(depth_h, int(math.ceil((y1 / max(1.0, float(image_h))) * float(depth_h)))))
        for gy in range(gy0, max(gy0, gy1)):
            for gx in range(gx0, max(gx0, gx1)):
                mask[gy * depth_w + gx] = True
    return mask, warnings


def _has_dynamic_track_ids(*, seg_payload: dict[str, Any] | None, dynamic_labels: set[str]) -> bool:
    payload = seg_payload if isinstance(seg_payload, dict) else {}
    segments = payload.get("segments")
    segments = segments if isinstance(segments, list) else []
    for row in segments:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label", "")).strip().lower()
        if dynamic_labels and label not in dynamic_labels:
            continue
        track_id = str(row.get("trackId", "")).strip()
        if track_id:
            return True
    return False


def _decode_seg_mask(seg_mask: Any, *, depth_w: int, depth_h: int) -> list[bool] | None:
    if not isinstance(seg_mask, dict):
        return None
    if str(seg_mask.get("format", "")).strip() != "rle_v1":
        return None
    size = seg_mask.get("size")
    if not isinstance(size, list) or len(size) != 2:
        return None
    h = _to_nonnegative_int(size[0], 0)
    w = _to_nonnegative_int(size[1], 0)
    if h <= 0 or w <= 0:
        return None
    if h != depth_h or w != depth_w:
        return None
    counts = seg_mask.get("counts")
    if not isinstance(counts, list):
        return None
    out = [False] * (h * w)
    cursor = 0
    value = 0
    for item in counts:
        try:
            run = int(item)
        except Exception:
            return None
        if run < 0:
            return None
        end = cursor + run
        if end > len(out):
            return None
        if value == 1:
            for idx in range(cursor, end):
                out[idx] = True
        cursor = end
        value = 1 - value
    if cursor != len(out):
        return None
    return out


def _dilate_u8_grid(values: list[int], width: int, height: int) -> list[int]:
    if width <= 0 or height <= 0 or not values:
        return values
    src = list(values)
    out = list(src)
    for y in range(height):
        for x in range(width):
            max_v = src[y * width + x]
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = src[ny * width + nx]
                    if neighbor > max_v:
                        max_v = neighbor
            out[y * width + x] = int(max_v)
    return out


def _decode_u8_grid(data_b64: str, h: int, w: int) -> list[int]:
    cell_count = max(0, int(h) * int(w))
    if cell_count <= 0:
        return []
    try:
        raw = base64.b64decode(data_b64.encode("ascii"), validate=False)
    except Exception:
        return [0] * cell_count
    data = list(raw[:cell_count])
    if len(data) < cell_count:
        data.extend([0] * (cell_count - len(data)))
    return [max(0, min(255, int(item))) for item in data]


def _extract_hotspots(values: list[int], h: int, w: int) -> list[dict[str, Any]]:
    if not values or h <= 0 or w <= 0:
        return []
    rows: list[dict[str, Any]] = []
    for idx, cost in enumerate(values):
        if int(cost) <= 0:
            continue
        r = idx // w
        c = idx % w
        rows.append({"cost": int(cost), "r": int(r), "c": int(c)})
    rows.sort(key=lambda row: (-int(row["cost"]), int(row["r"]), int(row["c"])))
    top = rows[:24]
    out: list[dict[str, Any]] = []
    for row in top:
        direction = _dir_from_col(int(row["c"]), w)
        distance = _distance_from_row(int(row["r"]), h)
        line = f"{direction}-{distance}:{int(row['cost'])}"
        out.append({"line": line, "direction": direction, "distance": distance, "cost": int(row["cost"])})
    return out


def _render_hotspots_fragment(hotspots: list[dict[str, Any]]) -> str:
    if not hotspots:
        return "[COSTMAP] hotspots: none"
    lines = [str(item.get("line", "")).strip() for item in hotspots if str(item.get("line", "")).strip()]
    if not lines:
        return "[COSTMAP] hotspots: none"
    return "[COSTMAP] hotspots: " + "; ".join(lines)


def _dir_from_col(col: int, width: int) -> str:
    if width <= 0:
        return "center"
    x = float(col) / float(max(1, width))
    if x < 0.33:
        return "left"
    if x > 0.67:
        return "right"
    return "center"


def _distance_from_row(row: int, height: int) -> str:
    if height <= 0:
        return "mid"
    y = float(row) / float(max(1, height))
    if y < 0.33:
        return "far"
    if y > 0.67:
        return "near"
    return "mid"


def _to_nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return int(default)
        return max(0, int(float(value)))
    except Exception:
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _try_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _token_approx(chars_total: int) -> int:
    if int(chars_total) <= 0:
        return 0
    return int(math.ceil(float(chars_total) / 4.0))
