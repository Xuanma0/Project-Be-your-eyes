from __future__ import annotations

import math
from typing import Any, Iterable


DEFAULT_SLAM_CONTEXT_BUDGET = {
    "maxChars": 512,
    "mode": "last_pose_and_health",
}

_ALLOWED_MODES = {"last_pose_and_health"}
_DEFAULT_POSE_WINDOW = 20


def build_slam_context_pack(
    *,
    run_id: str | None,
    frame_seq: int | None,
    events_v1: Iterable[dict[str, Any]] | None,
    budget: dict[str, Any] | None,
    slam_error: dict[str, Any] | None = None,
    alignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_budget = _normalize_budget(budget)
    max_chars = int(normalized_budget["maxChars"])
    mode = str(normalized_budget["mode"])

    events = _normalize_events(events_v1)
    resolved_run_id = str(run_id or "").strip() or _pick_run_id(events) or "slam-context"

    poses_all = _collect_slam_poses(events, run_id=resolved_run_id)
    requested_frame_seq = _to_nonnegative_int(frame_seq, 0)
    if requested_frame_seq > 0:
        poses_all = [row for row in poses_all if int(row.get("frameSeq", 0) or 0) <= requested_frame_seq]
    poses_window = poses_all[-_DEFAULT_POSE_WINDOW:]
    latest_pose = poses_window[-1] if poses_window else None
    output_frame_seq = int(latest_pose.get("frameSeq", 0) or 0) if isinstance(latest_pose, dict) else requested_frame_seq
    if output_frame_seq <= 0:
        output_frame_seq = 1

    tracking_state = _normalize_tracking_state(latest_pose.get("trackingState") if isinstance(latest_pose, dict) else None)
    tracking_rate = _safe_ratio(
        len([row for row in poses_window if _normalize_tracking_state(row.get("trackingState")) == "tracking"]),
        len(poses_window),
    )
    longest_lost_streak = _compute_longest_lost_streak(poses_window)
    speed_values, yaw_rate_values = _compute_motion_stats(poses_window)
    latest_speed = float(speed_values[-1]) if speed_values else None

    slam_error_payload = slam_error if isinstance(slam_error, dict) and bool(slam_error.get("present")) else {}
    ate_rmse = _to_nonnegative_float(slam_error_payload.get("ate_rmse_m"))
    rpe_trans_rmse = _to_nonnegative_float(slam_error_payload.get("rpe_trans_rmse_m"))
    has_slam_error = ate_rmse is not None or rpe_trans_rmse is not None

    alignment_payload = alignment if isinstance(alignment, dict) and bool(alignment.get("present")) else {}
    align_mode = str(alignment_payload.get("mode", "")).strip() or None
    residual_payload = alignment_payload.get("residualMs")
    residual_payload = residual_payload if isinstance(residual_payload, dict) else {}
    align_residual_p90 = _to_nonnegative_float(
        residual_payload.get("p90") if residual_payload else alignment_payload.get("residualP90Ms")
    )
    has_align = align_mode is not None or align_residual_p90 is not None

    health_line = _build_health_line(
        tracking_state=tracking_state,
        tracking_rate=tracking_rate,
        longest_lost_streak=longest_lost_streak,
        align_residual_p90=align_residual_p90,
        ate_rmse=ate_rmse,
        rpe_trans_rmse=rpe_trans_rmse,
        speed_p90=_percentile_float(speed_values, 90) if speed_values else None,
    )
    motion_line = _build_motion_line(speed_values=speed_values, yaw_rate_values=yaw_rate_values)
    pose_lines = _build_pose_lines(poses_window)

    full_lines = [health_line]
    if motion_line:
        full_lines.append(motion_line)
    full_lines.extend(pose_lines)
    full_prompt = "\n".join([line for line in full_lines if line]).strip()
    in_chars_total = len(full_prompt)

    kept_lines: list[str] = []
    remaining = max(0, int(max_chars))

    def _append_line(text: str) -> bool:
        nonlocal remaining
        if not text:
            return True
        if not kept_lines:
            if len(text) <= remaining:
                kept_lines.append(text)
                remaining -= len(text)
                return True
            kept_lines.append(text[:remaining])
            remaining = 0
            return False
        needed = 1 + len(text)
        if needed <= remaining:
            kept_lines.append(text)
            remaining -= needed
            return True
        if remaining > 1:
            kept_lines.append(text[: remaining - 1])
            remaining = 0
        return False

    _append_line(health_line)
    if motion_line and remaining > 0:
        _append_line(motion_line)
    poses_kept = 0
    for line in pose_lines:
        if remaining <= 0:
            break
        if _append_line(line):
            poses_kept += 1
        else:
            # Partial line is not a complete pose row.
            break
    prompt_fragment = "\n".join([line for line in kept_lines if line]).strip()
    out_chars_total = len(prompt_fragment)
    token_approx = _token_approx(out_chars_total)
    chars_dropped = max(0, in_chars_total - out_chars_total)
    poses_dropped = max(0, len(pose_lines) - poses_kept)

    motion_payload: dict[str, Any] = {}
    if latest_speed is not None:
        motion_payload["latestSpeedMps"] = round(max(0.0, float(latest_speed)), 6)
    if speed_values:
        motion_payload["speedMpsP50"] = round(max(0.0, _percentile_float(speed_values, 50)), 6)
        motion_payload["speedMpsP90"] = round(max(0.0, _percentile_float(speed_values, 90)), 6)
    if yaw_rate_values:
        motion_payload["yawRateDpsP90"] = round(max(0.0, _percentile_float(yaw_rate_values, 90)), 6)

    quality_payload: dict[str, Any] = {}
    if ate_rmse is not None:
        quality_payload["ateRmseM"] = round(float(ate_rmse), 6)
    if rpe_trans_rmse is not None:
        quality_payload["rpeTransRmseM"] = round(float(rpe_trans_rmse), 6)

    alignment_out: dict[str, Any] = {}
    if align_mode is not None:
        alignment_out["mode"] = align_mode
    if align_residual_p90 is not None:
        alignment_out["residualP90Ms"] = round(float(align_residual_p90), 6)

    summary = (
        f"mode={mode}; poses={len(poses_window) - poses_dropped}/{len(poses_window)}; "
        f"chars={out_chars_total}/{max_chars}; state={tracking_state}; dropped={poses_dropped}"
    )

    payload: dict[str, Any] = {
        "schemaVersion": "slam.context.v1",
        "runId": resolved_run_id,
        "frameSeq": int(output_frame_seq),
        "budget": {
            "maxChars": int(max_chars),
            "mode": mode,
        },
        "stats": {
            "in": {
                "poses": int(len(poses_window)),
                "hasSlamError": bool(has_slam_error),
                "hasAlign": bool(has_align),
                "charsTotal": int(in_chars_total),
            },
            "out": {
                "charsTotal": int(out_chars_total),
                "tokenApprox": int(token_approx),
            },
            "truncation": {
                "posesDropped": int(poses_dropped),
                "charsDropped": int(chars_dropped),
            },
        },
        "health": {
            "trackingState": tracking_state,
            "trackingRateWindow": round(max(0.0, min(1.0, tracking_rate)), 6),
            "longestLostStreak": int(longest_lost_streak),
        },
        "text": {
            "summary": summary,
            "promptFragment": prompt_fragment,
            "promptFragmentLength": int(len(prompt_fragment)),
        },
    }
    if motion_payload:
        payload["motion"] = motion_payload
    if quality_payload:
        payload["quality"] = quality_payload
    if alignment_out:
        payload["alignment"] = alignment_out
    return payload


def _normalize_events(events_v1: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in events_v1 or []:
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if isinstance(event, dict):
            rows.append(event)
    return rows


def _pick_run_id(events: list[dict[str, Any]]) -> str:
    for row in reversed(events):
        run_id = str(row.get("runId", "")).strip()
        if run_id:
            return run_id
    return "slam-context"


def _collect_slam_poses(events: list[dict[str, Any]], *, run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if str(event.get("name", "")).strip().lower() != "slam.pose":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        event_run_id = str(event.get("runId", "")).strip()
        if run_id and event_run_id and event_run_id != run_id:
            continue
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        pose = payload.get("pose")
        pose = pose if isinstance(pose, dict) else {}
        t_raw = pose.get("t")
        t_raw = t_raw if isinstance(t_raw, list) else []
        q_raw = pose.get("q")
        q_raw = q_raw if isinstance(q_raw, list) else []
        if len(t_raw) != 3 or len(q_raw) != 4:
            continue
        t_values: list[float] = []
        q_values: list[float] = []
        valid = True
        for value in t_raw:
            parsed = _to_float(value)
            if parsed is None:
                valid = False
                break
            t_values.append(float(parsed))
        if not valid:
            continue
        for value in q_raw:
            parsed = _to_float(value)
            if parsed is None:
                valid = False
                break
            q_values.append(float(parsed))
        if not valid:
            continue
        frame_seq = _to_nonnegative_int(event.get("frameSeq"), 0)
        if frame_seq <= 0:
            frame_seq = _to_nonnegative_int(payload.get("frameSeq"), 0)
        if frame_seq <= 0:
            continue
        ts_ms = _to_nonnegative_int(event.get("tsMs"), 0)
        rows.append(
            {
                "frameSeq": frame_seq,
                "tsMs": ts_ms,
                "trackingState": _normalize_tracking_state(payload.get("trackingState")),
                "t": t_values,
                "q": q_values,
            }
        )
    rows.sort(key=lambda row: (int(row.get("frameSeq", 0) or 0), int(row.get("tsMs", 0) or 0)))
    return rows


def _normalize_budget(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    max_chars = _to_nonnegative_int(source.get("maxChars"), int(DEFAULT_SLAM_CONTEXT_BUDGET["maxChars"]))
    mode_raw = str(source.get("mode", DEFAULT_SLAM_CONTEXT_BUDGET["mode"])).strip().lower()
    mode = mode_raw if mode_raw in _ALLOWED_MODES else str(DEFAULT_SLAM_CONTEXT_BUDGET["mode"])
    return {
        "maxChars": int(max_chars),
        "mode": mode,
    }


def _normalize_tracking_state(value: Any) -> str:
    state = str(value or "").strip().lower()
    if state in {"tracking", "lost", "relocalized"}:
        return state
    return "unknown"


def _compute_longest_lost_streak(poses: list[dict[str, Any]]) -> int:
    longest = 0
    current = 0
    for row in poses:
        state = _normalize_tracking_state(row.get("trackingState"))
        if state == "lost":
            current += 1
            if current > longest:
                longest = current
        else:
            current = 0
    return int(longest)


def _compute_motion_stats(poses: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    if len(poses) < 2:
        return [], []
    speed_values: list[float] = []
    yaw_rate_values: list[float] = []
    for prev, cur in zip(poses[:-1], poses[1:]):
        prev_t = prev.get("t")
        cur_t = cur.get("t")
        prev_t = prev_t if isinstance(prev_t, list) else []
        cur_t = cur_t if isinstance(cur_t, list) else []
        if len(prev_t) != 3 or len(cur_t) != 3:
            continue
        prev_ts = _to_nonnegative_int(prev.get("tsMs"), 0)
        cur_ts = _to_nonnegative_int(cur.get("tsMs"), 0)
        dt_ms = cur_ts - prev_ts
        if dt_ms <= 0:
            continue
        dist = math.sqrt(
            ((float(cur_t[0]) - float(prev_t[0])) ** 2)
            + ((float(cur_t[1]) - float(prev_t[1])) ** 2)
            + ((float(cur_t[2]) - float(prev_t[2])) ** 2)
        )
        speed_values.append(float(dist / (float(dt_ms) / 1000.0)))

        prev_q = prev.get("q")
        cur_q = cur.get("q")
        prev_q = prev_q if isinstance(prev_q, list) else []
        cur_q = cur_q if isinstance(cur_q, list) else []
        if len(prev_q) == 4 and len(cur_q) == 4:
            prev_yaw = _quat_to_yaw_deg(prev_q)
            cur_yaw = _quat_to_yaw_deg(cur_q)
            if prev_yaw is not None and cur_yaw is not None:
                delta = abs(cur_yaw - prev_yaw)
                if delta > 180.0:
                    delta = 360.0 - delta
                yaw_rate_values.append(float(delta / (float(dt_ms) / 1000.0)))
    return speed_values, yaw_rate_values


def _build_health_line(
    *,
    tracking_state: str,
    tracking_rate: float,
    longest_lost_streak: int,
    align_residual_p90: float | None,
    ate_rmse: float | None,
    rpe_trans_rmse: float | None,
    speed_p90: float | None,
) -> str:
    parts = [
        f"[SLAM] state={tracking_state}",
        f"rate={tracking_rate:.2f}",
        f"lostStreak={int(longest_lost_streak)}",
    ]
    if align_residual_p90 is not None:
        parts.append(f"alignP90={int(round(float(align_residual_p90)))}ms")
    if ate_rmse is not None:
        parts.append(f"ate={float(ate_rmse):.3f}")
    if rpe_trans_rmse is not None:
        parts.append(f"rpe={float(rpe_trans_rmse):.3f}")
    if speed_p90 is not None:
        parts.append(f"speedP90={float(speed_p90):.2f}m/s")
    return " ".join(parts)


def _build_motion_line(*, speed_values: list[float], yaw_rate_values: list[float]) -> str:
    if not speed_values and not yaw_rate_values:
        return ""
    parts = ["[SLAM_MOTION]"]
    if speed_values:
        parts.append(f"latest={float(speed_values[-1]):.2f}m/s")
        parts.append(f"p50={_percentile_float(speed_values, 50):.2f}m/s")
        parts.append(f"p90={_percentile_float(speed_values, 90):.2f}m/s")
    if yaw_rate_values:
        parts.append(f"yawP90={_percentile_float(yaw_rate_values, 90):.2f}deg/s")
    return " ".join(parts)


def _build_pose_lines(poses: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in reversed(poses):
        t = row.get("t")
        t = t if isinstance(t, list) else []
        if len(t) != 3:
            continue
        frame_seq = _to_nonnegative_int(row.get("frameSeq"), 0)
        state = _normalize_tracking_state(row.get("trackingState"))
        lines.append(
            "[SLAM_POSE] f={frame} state={state} t=[{x:.2f},{y:.2f},{z:.2f}]".format(
                frame=int(frame_seq),
                state=state,
                x=float(t[0]),
                y=float(t[1]),
                z=float(t[2]),
            )
        )
    return lines


def _quat_to_yaw_deg(q_values: list[float]) -> float | None:
    if len(q_values) != 4:
        return None
    x, y, z, w = float(q_values[0]), float(q_values[1]), float(q_values[2]), float(q_values[3])
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw_rad = math.atan2(siny_cosp, cosy_cosp)
    return math.degrees(yaw_rad)


def _token_approx(chars_total: int) -> int:
    if int(chars_total) <= 0:
        return 0
    return int(math.ceil(float(chars_total) / 4.0))


def _safe_ratio(num: int, den: int) -> float:
    if int(den) <= 0:
        return 0.0
    return float(num) / float(den)


def _percentile_float(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return float(ordered[0])
    percentile = max(0.0, min(100.0, float(p)))
    rank = (percentile / 100.0) * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return float(ordered[lower])
    fraction = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _to_nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return int(default)
        return max(0, int(float(value)))
    except Exception:
        return int(default)


def _to_nonnegative_float(value: Any) -> float | None:
    parsed = _to_float(value)
    if parsed is None:
        return None
    return max(0.0, float(parsed))


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None
