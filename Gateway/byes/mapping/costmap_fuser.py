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
    "shiftGateEnabled": True,
    "minTrackingRate": 0.6,
    "maxLostStreak": 2,
    "maxAlignResidualP90Ms": 80.0,
    "maxAteRmseM": 0.25,
    "maxRpeTransRmseM": 0.1,
    "slamTrajPreferred": "auto",
    "slamTrajAllowed": ("online", "final"),
    "slamQualityByModel": {},
    "occupiedThresh": 200,
}


@dataclass
class _FuserState:
    fused: np.ndarray
    prev_occupied: np.ndarray
    pose_t_by_model: dict[str, tuple[float, float]]
    history: list[dict[str, Any]]


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
        shift_gate_enabled = bool(normalized["shiftGateEnabled"])
        resolution_m = float(_to_float(_nested(raw_costmap_payload, ["grid", "resolutionM"]), 0.1))
        resolution_m = max(0.001, resolution_m)

        raw_grid, grid_h, grid_w, warnings = _decode_costmap_grid(raw_costmap_payload)
        run_key = str(run_id or "").strip() or "costmap-fused-run"
        current_pose = _extract_pose_xy(slam_payload)
        current_model = _extract_slam_model_name(slam_payload)
        current_label = _model_to_traj_label(current_model)
        current_state = _extract_tracking_state(slam_payload)
        allowed_labels = _normalize_allowed_labels(normalized.get("slamTrajAllowed"))
        preferred_label = _normalize_preferred_label(normalized.get("slamTrajPreferred"), allowed_labels)
        slam_quality_by_model = normalized.get("slamQualityByModel")
        slam_quality_by_model = slam_quality_by_model if isinstance(slam_quality_by_model, dict) else {}

        with self._lock:
            state = self._states.get(run_key)
            if state is None or state.fused.shape != raw_grid.shape:
                state = _FuserState(
                    fused=np.zeros_like(raw_grid, dtype=np.float32),
                    prev_occupied=np.zeros_like(raw_grid, dtype=np.uint8),
                    pose_t_by_model={},
                    history=[],
                )

            prev_occupied = np.array(state.prev_occupied, copy=True)
            fused_prev = np.array(state.fused, copy=True)
            fused_work = fused_prev * decay

            raw_dynamic_temporal_used = bool(_nested(raw_costmap_payload, ["stats", "dynamicTemporalUsed"]))
            raw_dynamic_tracks_used = max(0, _to_int(_nested(raw_costmap_payload, ["stats", "dynamicTracksUsed"]), 0))
            raw_dynamic_mask_used = bool(_nested(raw_costmap_payload, ["stats", "dynamicMaskUsed"]))

            history_row: dict[str, Any] = {
                "frameSeq": int(max(1, int(frame_seq))),
                "dynamicTemporalUsed": bool(raw_dynamic_temporal_used),
                "dynamicTracksUsed": int(raw_dynamic_tracks_used),
                "dynamicMaskUsed": bool(raw_dynamic_mask_used),
            }
            if current_model:
                history_row["model"] = current_model
                history_row["label"] = current_label
                history_row["trackingState"] = current_state
            state.history.append(history_row)
            max_history = max(20, int(max(1, int(normalized["windowFrames"]))) * 4)
            if len(state.history) > max_history:
                state.history = state.history[-max_history:]

            selected_label, selected_model = _select_slam_model(
                preferred_label=preferred_label,
                allowed_labels=allowed_labels,
                current_model=current_model,
                current_label=current_label,
                known_pose_models=set(state.pose_t_by_model.keys()),
                history=state.history,
            )
            selected_pose = current_pose if (selected_model and current_model and selected_model == current_model) else None
            if selected_pose is None and current_pose is not None and (selected_model is None or current_model is None):
                selected_pose = current_pose
            prev_pose = state.pose_t_by_model.get(selected_model, None) if selected_model else None
            tracking_rate, longest_lost_streak = _tracking_window_stats(
                state.history,
                label=selected_label,
                window_frames=int(max(1, int(normalized["windowFrames"]))),
            )
            dynamic_mask_used_rate_window = _dynamic_mask_used_rate(
                state.history,
                window_frames=int(max(1, int(normalized["windowFrames"]))),
            )
            align_residual_p90_ms = _pick_slam_quality_metric(
                slam_quality_by_model,
                selected_model=selected_model,
                selected_label=selected_label,
                metric_key="align_residual_p90_ms",
            )
            ate_rmse_m = _pick_slam_quality_metric(
                slam_quality_by_model,
                selected_model=selected_model,
                selected_label=selected_label,
                metric_key="ate_rmse_m",
            )
            rpe_trans_rmse_m = _pick_slam_quality_metric(
                slam_quality_by_model,
                selected_model=selected_model,
                selected_label=selected_label,
                metric_key="rpe_trans_rmse_m",
            )

            gate = _evaluate_shift_gate(
                shift_enabled=shift_enabled,
                shift_gate_enabled=shift_gate_enabled,
                selected_model=selected_model,
                selected_pose=selected_pose,
                prev_pose=prev_pose,
                tracking_rate=tracking_rate,
                longest_lost_streak=longest_lost_streak,
                align_residual_p90_ms=align_residual_p90_ms,
                ate_rmse_m=ate_rmse_m,
                rpe_trans_rmse_m=rpe_trans_rmse_m,
                min_tracking_rate=float(normalized["minTrackingRate"]),
                max_lost_streak=int(normalized["maxLostStreak"]),
                max_align_residual_p90_ms=float(normalized["maxAlignResidualP90Ms"]),
                max_ate_rmse_m=float(normalized["maxAteRmseM"]),
                max_rpe_trans_rmse_m=float(normalized["maxRpeTransRmseM"]),
            )

            shift_cells: tuple[int, int] | None = None
            shift_used = False
            if gate["allowed"] and prev_pose is not None and selected_pose is not None:
                delta_x = float(selected_pose[0]) - float(prev_pose[0])
                delta_y = float(selected_pose[1]) - float(prev_pose[1])
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
            if selected_model and selected_pose is not None:
                state.pose_t_by_model[selected_model] = selected_pose
            self._states[run_key] = state

        dynamic_filtered_rate = _to_unit_float(_nested(raw_costmap_payload, ["stats", "dynamicFilteredRate"]))
        dynamic_temporal_used = bool(_nested(raw_costmap_payload, ["stats", "dynamicTemporalUsed"]))
        dynamic_tracks_used = max(0, _to_int(_nested(raw_costmap_payload, ["stats", "dynamicTracksUsed"]), 0))
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
                "method": "ema_shift_v1" if (shift_enabled and gate["allowed"]) else "ema_v1",
                "alpha": float(round(alpha, 6)),
                "decay": float(round(decay, 6)),
                "windowFrames": int(max(1, int(normalized["windowFrames"]))),
                "shiftUsed": bool(shift_used),
                "shiftCells": [int(shift_cells[0]), int(shift_cells[1])] if shift_cells is not None else None,
                "gate": {
                    "allowed": bool(gate["allowed"]),
                    "reasons": [str(item) for item in gate["reasons"]],
                    "slamModel": selected_model,
                },
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
                "dynamicTemporalUsed": bool(dynamic_temporal_used),
                "dynamicTracksUsed": int(dynamic_tracks_used),
                "dynamicMaskUsedRateWindow": float(round(dynamic_mask_used_rate_window, 6)),
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
    shift_gate_enabled = bool(source.get("shiftGateEnabled", DEFAULT_COSTMAP_FUSED_CONFIG["shiftGateEnabled"]))
    min_tracking_rate = _to_float(source.get("minTrackingRate"), DEFAULT_COSTMAP_FUSED_CONFIG["minTrackingRate"])
    max_lost_streak = _to_int(source.get("maxLostStreak"), DEFAULT_COSTMAP_FUSED_CONFIG["maxLostStreak"])
    max_align_residual_p90_ms = _to_float(
        source.get("maxAlignResidualP90Ms"),
        DEFAULT_COSTMAP_FUSED_CONFIG["maxAlignResidualP90Ms"],
    )
    max_ate_rmse_m = _to_float(source.get("maxAteRmseM"), DEFAULT_COSTMAP_FUSED_CONFIG["maxAteRmseM"])
    max_rpe_trans_rmse_m = _to_float(source.get("maxRpeTransRmseM"), DEFAULT_COSTMAP_FUSED_CONFIG["maxRpeTransRmseM"])
    slam_traj_preferred = str(source.get("slamTrajPreferred", DEFAULT_COSTMAP_FUSED_CONFIG["slamTrajPreferred"])).strip().lower()
    if slam_traj_preferred not in {"auto", "online", "final"}:
        slam_traj_preferred = str(DEFAULT_COSTMAP_FUSED_CONFIG["slamTrajPreferred"])
    raw_allowed = source.get("slamTrajAllowed", DEFAULT_COSTMAP_FUSED_CONFIG["slamTrajAllowed"])
    allowed: list[str] = []
    if isinstance(raw_allowed, (list, tuple)):
        for item in raw_allowed:
            text = _normalize_traj_label(item)
            if text and text not in allowed:
                allowed.append(text)
    if not allowed:
        allowed = list(DEFAULT_COSTMAP_FUSED_CONFIG["slamTrajAllowed"])
    slam_quality_by_model = source.get("slamQualityByModel")
    if not isinstance(slam_quality_by_model, dict):
        slam_quality_by_model = {}
    return {
        "alpha": max(0.0, min(1.0, alpha)),
        "decay": max(0.0, min(1.0, decay)),
        "windowFrames": max(1, int(window)),
        "occupiedThresh": max(0, min(255, int(occupied_thresh))),
        "shiftEnabled": bool(shift_enabled),
        "shiftGateEnabled": bool(shift_gate_enabled),
        "minTrackingRate": max(0.0, min(1.0, float(min_tracking_rate))),
        "maxLostStreak": max(0, int(max_lost_streak)),
        "maxAlignResidualP90Ms": max(0.0, float(max_align_residual_p90_ms)),
        "maxAteRmseM": max(0.0, float(max_ate_rmse_m)),
        "maxRpeTransRmseM": max(0.0, float(max_rpe_trans_rmse_m)),
        "slamTrajPreferred": slam_traj_preferred,
        "slamTrajAllowed": tuple(allowed),
        "slamQualityByModel": slam_quality_by_model,
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


def _extract_tracking_state(payload: dict[str, Any] | None) -> str:
    row = payload if isinstance(payload, dict) else {}
    raw = str(row.get("trackingState", "")).strip().lower()
    if raw in {"tracking", "lost", "relocalized", "initializing"}:
        return raw
    return "tracking"


def _extract_slam_model_name(payload: dict[str, Any] | None) -> str | None:
    row = payload if isinstance(payload, dict) else {}
    text = str(row.get("model", "")).strip()
    return text or None


def _normalize_traj_label(raw: Any) -> str | None:
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if "final" in text:
        return "final"
    if "online" in text:
        return "online"
    if text in {"final", "online"}:
        return text
    return None


def _model_to_traj_label(model_name: str | None) -> str | None:
    return _normalize_traj_label(model_name)


def _normalize_allowed_labels(raw_allowed: Any) -> tuple[str, ...]:
    labels: list[str] = []
    if isinstance(raw_allowed, (list, tuple)):
        for item in raw_allowed:
            text = _normalize_traj_label(item)
            if text and text not in labels:
                labels.append(text)
    if not labels:
        labels = ["online", "final"]
    return tuple(labels)


def _normalize_preferred_label(raw_preferred: Any, allowed: tuple[str, ...]) -> str:
    preferred = str(raw_preferred or "auto").strip().lower()
    if preferred not in {"auto", "online", "final"}:
        preferred = "auto"
    if preferred != "auto" and preferred not in allowed:
        preferred = "auto"
    return preferred


def _select_slam_model(
    *,
    preferred_label: str,
    allowed_labels: tuple[str, ...],
    current_model: str | None,
    current_label: str | None,
    known_pose_models: set[str],
    history: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    candidates_by_label: dict[str, list[str]] = {}
    for model_name in sorted(known_pose_models):
        label = _model_to_traj_label(model_name)
        if not label:
            continue
        candidates_by_label.setdefault(label, []).append(model_name)
    if current_model and current_label:
        candidates_by_label.setdefault(current_label, [])
        if current_model not in candidates_by_label[current_label]:
            candidates_by_label[current_label].append(current_model)

    def pick_label() -> str | None:
        if preferred_label in {"online", "final"}:
            return preferred_label
        for label in ("final", "online"):
            if label in allowed_labels and candidates_by_label.get(label):
                return label
        if current_label and current_label in allowed_labels:
            return current_label
        for label in allowed_labels:
            if candidates_by_label.get(label):
                return label
        return allowed_labels[0] if allowed_labels else None

    selected_label = pick_label()
    if not selected_label:
        return None, None
    if current_model and _model_to_traj_label(current_model) == selected_label:
        return selected_label, current_model
    models = candidates_by_label.get(selected_label, [])
    if models:
        # Prefer the most recent model seen in history for the selected label.
        for row in reversed(history):
            if not isinstance(row, dict):
                continue
            model_text = str(row.get("model", "")).strip()
            if model_text and _model_to_traj_label(model_text) == selected_label and model_text in models:
                return selected_label, model_text
        return selected_label, models[-1]
    return selected_label, f"pyslam-{selected_label}"


def _tracking_window_stats(
    history: list[dict[str, Any]],
    *,
    label: str | None,
    window_frames: int,
) -> tuple[float | None, int | None]:
    if not history:
        return None, None
    rows = []
    for row in history:
        if not isinstance(row, dict):
            continue
        if label and _model_to_traj_label(str(row.get("model", "")).strip()) != label:
            continue
        state = str(row.get("trackingState", "")).strip().lower()
        if state not in {"tracking", "lost", "relocalized", "initializing"}:
            continue
        rows.append(state)
    if not rows:
        return None, None
    rows = rows[-max(1, int(window_frames)) :]
    tracking = sum(1 for item in rows if item == "tracking")
    tracking_rate = float(tracking) / float(max(1, len(rows)))
    longest_lost = 0
    current_lost = 0
    for item in rows:
        if item == "lost":
            current_lost += 1
            if current_lost > longest_lost:
                longest_lost = current_lost
        else:
            current_lost = 0
    return tracking_rate, int(longest_lost)


def _dynamic_mask_used_rate(history: list[dict[str, Any]], *, window_frames: int) -> float:
    if not history:
        return 0.0
    rows = history[-max(1, int(window_frames)) :]
    if not rows:
        return 0.0
    used = 0
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("dynamicMaskUsed")
        if not isinstance(value, bool):
            continue
        total += 1
        if value:
            used += 1
    if total <= 0:
        return 0.0
    return float(used) / float(total)


def _pick_slam_quality_metric(
    quality_by_model: dict[str, Any],
    *,
    selected_model: str | None,
    selected_label: str | None,
    metric_key: str,
) -> float | None:
    if not isinstance(quality_by_model, dict):
        return None
    candidates: list[dict[str, Any]] = []
    if selected_model:
        payload = quality_by_model.get(selected_model)
        if isinstance(payload, dict):
            candidates.append(payload)
    if selected_label:
        payload = quality_by_model.get(selected_label)
        if isinstance(payload, dict):
            candidates.append(payload)
    if selected_model:
        normalized_key = selected_model.lower()
        for key, payload in quality_by_model.items():
            if not isinstance(payload, dict):
                continue
            if str(key).strip().lower() == normalized_key:
                candidates.append(payload)
    for payload in candidates:
        value = payload.get(metric_key)
        try:
            if value is None:
                continue
            return float(value)
        except Exception:
            continue
    return None


def _evaluate_shift_gate(
    *,
    shift_enabled: bool,
    shift_gate_enabled: bool,
    selected_model: str | None,
    selected_pose: tuple[float, float] | None,
    prev_pose: tuple[float, float] | None,
    tracking_rate: float | None,
    longest_lost_streak: int | None,
    align_residual_p90_ms: float | None,
    ate_rmse_m: float | None,
    rpe_trans_rmse_m: float | None,
    min_tracking_rate: float,
    max_lost_streak: int,
    max_align_residual_p90_ms: float,
    max_ate_rmse_m: float,
    max_rpe_trans_rmse_m: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not shift_enabled:
        reasons.append("shift_disabled")
        return {"allowed": False, "reasons": reasons}
    if selected_model is None or selected_pose is None or prev_pose is None:
        reasons.append("slam_missing")
        return {"allowed": False, "reasons": reasons}
    if not shift_gate_enabled:
        return {"allowed": True, "reasons": reasons}
    if tracking_rate is not None and float(tracking_rate) < float(min_tracking_rate):
        reasons.append("tracking_rate_low")
    if longest_lost_streak is not None and int(longest_lost_streak) > int(max_lost_streak):
        reasons.append("lost_streak_high")
    if align_residual_p90_ms is not None and float(align_residual_p90_ms) > float(max_align_residual_p90_ms):
        reasons.append("align_residual_high")
    slam_error_high = False
    if ate_rmse_m is not None and float(ate_rmse_m) > float(max_ate_rmse_m):
        slam_error_high = True
    if rpe_trans_rmse_m is not None and float(rpe_trans_rmse_m) > float(max_rpe_trans_rmse_m):
        slam_error_high = True
    if slam_error_high:
        reasons.append("slam_error_high")
    return {"allowed": len(reasons) == 0, "reasons": reasons}


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
