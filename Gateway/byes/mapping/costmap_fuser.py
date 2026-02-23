from __future__ import annotations

import base64
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

DEFAULT_COSTMAP_FUSED_CONFIG = {
    "alpha": 0.6,
    "decay": 0.95,
    "windowFrames": 10,
    "shiftEnabled": True,
    "occupiedThresh": 200,
}


@dataclass
class _FuserState:
    fused: np.ndarray
    prev_occupied: np.ndarray
    pose_t: tuple[float, float] | None


class CostmapFuser:
    def __init__(self) -> None:
        self._states: dict[str, _FuserState] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._states.clear()

    def update(
        self,
        *,
        run_id: str,
        frame_seq: int,
        raw_costmap_payload: dict[str, Any] | None,
        slam_payload: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        backend: str | None = "local",
        model: str | None = "local-costmap-fused-v1",
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_fused_config(config)
        alpha = float(normalized["alpha"])
        decay = float(normalized["decay"])
        occupied_thresh = int(normalized["occupiedThresh"])
        shift_enabled = bool(normalized["shiftEnabled"])
        resolution_m = float(_to_float(_nested(raw_costmap_payload, ["grid", "resolutionM"]), 0.1))
        resolution_m = max(0.001, resolution_m)

        raw_grid, grid_h, grid_w, warnings = _decode_costmap_grid(raw_costmap_payload)
        run_key = str(run_id or "").strip() or "costmap-fused-run"
        current_pose = _extract_pose_xy(slam_payload)

        with self._lock:
            state = self._states.get(run_key)
            if state is None or state.fused.shape != raw_grid.shape:
                state = _FuserState(
                    fused=np.zeros_like(raw_grid, dtype=np.float32),
                    prev_occupied=np.zeros_like(raw_grid, dtype=np.uint8),
                    pose_t=None,
                )

            prev_occupied = np.array(state.prev_occupied, copy=True)
            fused_prev = np.array(state.fused, copy=True)
            fused_work = fused_prev * decay

            shift_cells: tuple[int, int] | None = None
            shift_used = False
            if shift_enabled and state.pose_t is not None and current_pose is not None:
                delta_x = float(current_pose[0]) - float(state.pose_t[0])
                delta_y = float(current_pose[1]) - float(state.pose_t[1])
                dx_cells = int(round(delta_x / resolution_m))
                dy_cells = int(round(delta_y / resolution_m))
                if dx_cells != 0 or dy_cells != 0:
                    fused_work = _shift_grid_int(fused_work, dx_cells=dx_cells, dy_cells=dy_cells)
                    shift_cells = (dx_cells, dy_cells)
                    shift_used = True

            ema = alpha * raw_grid.astype(np.float32) + (1.0 - alpha) * fused_work
            fused_next = np.maximum(fused_work, ema)
            fused_u8 = np.clip(np.rint(fused_next), 0, 255).astype(np.uint8)
            occupied = (fused_u8 >= occupied_thresh).astype(np.uint8)

            iou_prev = _binary_iou(prev_occupied, occupied)
            flicker_prev = _binary_flicker(prev_occupied, occupied)
            hotspot_count = int(np.sum(occupied > 0))

            state.fused = fused_next
            state.prev_occupied = occupied
            state.pose_t = current_pose if current_pose is not None else state.pose_t
            self._states[run_key] = state

        dynamic_filtered_rate = _to_unit_float(_nested(raw_costmap_payload, ["stats", "dynamicFilteredRate"]))
        sources = _nested(raw_costmap_payload, ["stats", "sources"])
        sources = sources if isinstance(sources, dict) else {}
        source_depth = bool(sources.get("depth"))
        source_seg = bool(sources.get("seg"))
        source_slam = bool(sources.get("slam")) or current_pose is not None

        occupied_cells = int(np.sum(fused_u8 > 0))
        mean_cost = float(np.mean(fused_u8)) if fused_u8.size > 0 else 0.0
        max_cost = int(np.max(fused_u8)) if fused_u8.size > 0 else 0

        return {
            "schemaVersion": "byes.costmap_fused.v1",
            "runId": run_key,
            "frameSeq": int(max(1, int(frame_seq))),
            "frame": "local",
            "fuse": {
                "method": "ema_shift_v1" if shift_enabled else "ema_v1",
                "alpha": float(round(alpha, 6)),
                "decay": float(round(decay, 6)),
                "windowFrames": int(max(1, int(normalized["windowFrames"]))),
                "shiftUsed": bool(shift_used),
                "shiftCells": [int(shift_cells[0]), int(shift_cells[1])] if shift_cells is not None else None,
            },
            "grid": {
                "format": "grid_u8_cost_v1",
                "size": [int(grid_h), int(grid_w)],
                "resolutionM": float(resolution_m),
                "origin": {"x": 0.0, "y": 0.0},
                "dataB64": base64.b64encode(fused_u8.tobytes(order="C")).decode("ascii"),
            },
            "stats": {
                "occupiedCells": int(occupied_cells),
                "meanCost": float(round(mean_cost, 6)),
                "maxCost": int(max_cost),
                "dynamicFilteredRate": float(round(dynamic_filtered_rate, 6)),
                "stability": {
                    "iouPrev": None if iou_prev is None else float(round(iou_prev, 6)),
                    "flickerRatePrev": None if flicker_prev is None else float(round(flicker_prev, 6)),
                    "hotspotCount": int(hotspot_count),
                },
                "sources": {
                    "depth": bool(source_depth),
                    "seg": bool(source_seg),
                    "slam": bool(source_slam),
                },
            },
            "backend": str(backend).strip() if backend is not None else None,
            "model": str(model).strip() if model is not None else None,
            "endpoint": str(endpoint).strip() if endpoint else None,
            "warningsCount": int(max(0, warnings)),
        }


def _normalize_fused_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    alpha = _to_float(source.get("alpha"), DEFAULT_COSTMAP_FUSED_CONFIG["alpha"])
    decay = _to_float(source.get("decay"), DEFAULT_COSTMAP_FUSED_CONFIG["decay"])
    window = _to_int(source.get("windowFrames"), DEFAULT_COSTMAP_FUSED_CONFIG["windowFrames"])
    occupied_thresh = _to_int(source.get("occupiedThresh"), DEFAULT_COSTMAP_FUSED_CONFIG["occupiedThresh"])
    shift_enabled = bool(source.get("shiftEnabled", DEFAULT_COSTMAP_FUSED_CONFIG["shiftEnabled"]))
    return {
        "alpha": max(0.0, min(1.0, alpha)),
        "decay": max(0.0, min(1.0, decay)),
        "windowFrames": max(1, int(window)),
        "occupiedThresh": max(0, min(255, int(occupied_thresh))),
        "shiftEnabled": bool(shift_enabled),
    }


def _decode_costmap_grid(payload: dict[str, Any] | None) -> tuple[np.ndarray, int, int, int]:
    warnings = 0
    grid = _nested(payload, ["grid"])
    grid = grid if isinstance(grid, dict) else {}
    size = grid.get("size")
    size = size if isinstance(size, list) else []
    h = _to_int(size[0], 0) if len(size) > 0 else 0
    w = _to_int(size[1], 0) if len(size) > 1 else 0
    if h <= 0 or w <= 0:
        return np.zeros((32, 32), dtype=np.uint8), 32, 32, warnings + 1
    data_b64 = str(grid.get("dataB64", "")).strip()
    if not data_b64:
        return np.zeros((h, w), dtype=np.uint8), h, w, warnings + 1
    try:
        data = base64.b64decode(data_b64.encode("ascii"), validate=False)
    except Exception:
        return np.zeros((h, w), dtype=np.uint8), h, w, warnings + 1
    expected = h * w
    if len(data) != expected:
        warnings += 1
        if len(data) < expected:
            data = data + bytes(expected - len(data))
        else:
            data = data[:expected]
    arr = np.frombuffer(data, dtype=np.uint8).reshape((h, w))
    return np.array(arr, copy=True), h, w, warnings


def _shift_grid_int(grid: np.ndarray, *, dx_cells: int, dy_cells: int) -> np.ndarray:
    if dx_cells == 0 and dy_cells == 0:
        return np.array(grid, copy=True)
    out = np.roll(grid, shift=(dy_cells, dx_cells), axis=(0, 1))
    h, w = out.shape
    if dy_cells > 0:
        out[:dy_cells, :] = 0
    elif dy_cells < 0:
        out[h + dy_cells :, :] = 0
    if dx_cells > 0:
        out[:, :dx_cells] = 0
    elif dx_cells < 0:
        out[:, w + dx_cells :] = 0
    return out


def _extract_pose_xy(payload: dict[str, Any] | None) -> tuple[float, float] | None:
    row = payload if isinstance(payload, dict) else {}
    pose = row.get("pose")
    pose = pose if isinstance(pose, dict) else {}
    t = pose.get("t")
    if not isinstance(t, list) or len(t) < 2:
        return None
    try:
        x = float(t[0])
    except Exception:
        return None
    # Use x/z when available; fallback to x/y.
    try:
        y = float(t[2]) if len(t) >= 3 else float(t[1])
    except Exception:
        try:
            y = float(t[1])
        except Exception:
            return None
    return (x, y)


def _binary_iou(prev_occ: np.ndarray, curr_occ: np.ndarray) -> float | None:
    union = np.logical_or(prev_occ > 0, curr_occ > 0)
    union_count = int(np.sum(union))
    if union_count <= 0:
        return None
    inter = np.logical_and(prev_occ > 0, curr_occ > 0)
    inter_count = int(np.sum(inter))
    return float(inter_count) / float(union_count)


def _binary_flicker(prev_occ: np.ndarray, curr_occ: np.ndarray) -> float | None:
    total = int(prev_occ.size)
    if total <= 0:
        return None
    xor = np.logical_xor(prev_occ > 0, curr_occ > 0)
    return float(int(np.sum(xor))) / float(total)


def _nested(payload: dict[str, Any] | None, path: list[str]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _to_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _to_unit_float(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, parsed))
