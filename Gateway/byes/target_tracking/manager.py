from __future__ import annotations

from typing import Any

from .store import TargetTrackingSession


def build_target_session_payload(session: TargetTrackingSession, *, status: str, reason: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": "byes.target.session.v1",
        "sessionId": session.session_id,
        "deviceId": session.device_id,
        "runId": session.run_id,
        "status": str(status or "active").strip() or "active",
        "tracker": session.tracker,
        "roi": dict(session.roi),
        "prompt": session.prompt,
        "seg": {
            "enabled": bool(session.seg_enabled),
            "mode": session.seg_mode,
        },
        "createdTsMs": int(session.created_ts_ms),
        "updatedTsMs": int(session.updated_ts_ms),
    }
    if reason:
        payload["reason"] = str(reason).strip()
    return payload


def select_target_from_det_payload(
    det_payload: dict[str, Any] | None,
    *,
    prompt: str | None,
    roi: dict[str, float] | None,
) -> dict[str, Any] | None:
    if not isinstance(det_payload, dict):
        return None
    rows = det_payload.get("objects")
    if not isinstance(rows, list) or not rows:
        return None
    prompt_token = str(prompt or "").strip().lower()
    roi_norm = roi if isinstance(roi, dict) else None

    def inside_roi(obj: dict[str, Any]) -> bool:
        if roi_norm is None:
            return True
        box = obj.get("box_norm")
        if not isinstance(box, list) or len(box) != 4:
            return True
        try:
            x0, y0, x1, y1 = [float(v) for v in box]
        except Exception:
            return True
        cx = (x0 + x1) * 0.5
        cy = (y0 + y1) * 0.5
        return (
            cx >= float(roi_norm.get("x", 0.0))
            and cy >= float(roi_norm.get("y", 0.0))
            and cx <= float(roi_norm.get("x", 0.0)) + float(roi_norm.get("w", 1.0))
            and cy <= float(roi_norm.get("y", 0.0)) + float(roi_norm.get("h", 1.0))
        )

    candidates: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label", "")).strip()
        if prompt_token and prompt_token not in label.lower():
            continue
        if not inside_roi(raw):
            continue
        candidates.append(raw)

    if not candidates:
        for raw in rows:
            if isinstance(raw, dict):
                candidates.append(raw)

    if not candidates:
        return None

    candidates.sort(key=lambda row: float(row.get("conf", 0.0) or 0.0), reverse=True)
    return candidates[0]


def build_target_update_payload(
    session: TargetTrackingSession,
    *,
    step: int,
    det_payload: dict[str, Any] | None,
    seg_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    selected = select_target_from_det_payload(det_payload, prompt=session.prompt, roi=session.roi)
    target_payload: dict[str, Any] | None = None
    if isinstance(selected, dict):
        target_payload = {
            "label": str(selected.get("label", "")).strip() or "unknown",
            "conf": float(selected.get("conf", 0.0) or 0.0),
            "boxNorm": selected.get("box_norm") if isinstance(selected.get("box_norm"), list) else None,
            "boxXyxy": selected.get("box_xyxy") if isinstance(selected.get("box_xyxy"), list) else None,
        }
        if isinstance(selected.get("mask"), dict):
            target_payload["mask"] = dict(selected.get("mask"))

    payload: dict[str, Any] = {
        "schemaVersion": "byes.target.update.v1",
        "sessionId": session.session_id,
        "deviceId": session.device_id,
        "runId": session.run_id,
        "step": int(max(1, step)),
        "tracker": session.tracker,
        "roi": dict(session.roi),
        "prompt": session.prompt,
        "target": target_payload,
        "hasDetection": bool(target_payload is not None),
        "seg": {
            "enabled": bool(session.seg_enabled),
            "mode": session.seg_mode,
            "payloadPresent": isinstance(seg_payload, dict),
        },
        "updatedTsMs": int(session.updated_ts_ms),
    }
    return payload
