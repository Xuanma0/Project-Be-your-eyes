from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class TargetTrackingSession:
    session_id: str
    device_id: str
    run_id: str
    created_ts_ms: int
    updated_ts_ms: int
    roi: dict[str, float]
    prompt: str | None
    tracker: str
    seg_enabled: bool
    seg_mode: str | None

    @property
    def age_ms(self) -> int:
        return max(0, _now_ms() - int(self.updated_ts_ms))


class TargetTrackingStore:
    def __init__(self, *, ttl_ms: int = 30_000, max_entries: int = 128) -> None:
        self._ttl_ms = max(1000, int(ttl_ms))
        self._max_entries = max(1, int(max_entries))
        self._sessions: OrderedDict[str, TargetTrackingSession] = OrderedDict()
        self._latest_session_by_device: dict[str, str] = {}

    def reset(self) -> None:
        self._sessions.clear()
        self._latest_session_by_device.clear()

    def start_session(
        self,
        *,
        device_id: str,
        run_id: str,
        roi: dict[str, Any],
        prompt: str | None,
        tracker: str,
        seg_enabled: bool,
        seg_mode: str | None,
        session_id: str | None = None,
    ) -> TargetTrackingSession:
        now_ms = _now_ms()
        self._purge(now_ms)
        normalized_device = str(device_id or "default").strip() or "default"
        sid = str(session_id or "").strip() or f"trk_{normalized_device}_{uuid.uuid4().hex[:8]}"
        session = TargetTrackingSession(
            session_id=sid,
            device_id=normalized_device,
            run_id=str(run_id or "").strip() or "unknown-run",
            created_ts_ms=now_ms,
            updated_ts_ms=now_ms,
            roi=_normalize_roi_dict(roi),
            prompt=str(prompt or "").strip() or None,
            tracker=_normalize_tracker(tracker),
            seg_enabled=bool(seg_enabled),
            seg_mode=str(seg_mode or "").strip() or None,
        )
        self._sessions[sid] = session
        self._sessions.move_to_end(sid, last=True)
        self._latest_session_by_device[normalized_device] = sid
        while len(self._sessions) > self._max_entries:
            dropped_sid, dropped = self._sessions.popitem(last=False)
            if self._latest_session_by_device.get(dropped.device_id) == dropped_sid:
                self._latest_session_by_device.pop(dropped.device_id, None)
        return session

    def get_session(self, *, device_id: str, session_id: str | None = None) -> TargetTrackingSession | None:
        now_ms = _now_ms()
        self._purge(now_ms)
        normalized_device = str(device_id or "default").strip() or "default"
        sid = str(session_id or "").strip()
        if not sid:
            sid = self._latest_session_by_device.get(normalized_device, "")
        if not sid:
            return None
        row = self._sessions.get(sid)
        if row is None:
            return None
        if row.device_id != normalized_device:
            return None
        return row

    def touch_session(self, session: TargetTrackingSession) -> TargetTrackingSession:
        now_ms = _now_ms()
        session.updated_ts_ms = now_ms
        self._sessions[session.session_id] = session
        self._sessions.move_to_end(session.session_id, last=True)
        self._latest_session_by_device[session.device_id] = session.session_id
        self._purge(now_ms)
        return session

    def stop_session(self, *, device_id: str, session_id: str | None = None) -> TargetTrackingSession | None:
        normalized_device = str(device_id or "default").strip() or "default"
        sid = str(session_id or "").strip() or self._latest_session_by_device.get(normalized_device, "")
        if not sid:
            return None
        row = self._sessions.get(sid)
        if row is None or row.device_id != normalized_device:
            return None
        self._sessions.pop(sid, None)
        if self._latest_session_by_device.get(normalized_device) == sid:
            self._latest_session_by_device.pop(normalized_device, None)
        return row

    def _purge(self, now_ms: int) -> None:
        cutoff = now_ms - int(self._ttl_ms)
        stale_ids = [sid for sid, row in self._sessions.items() if int(row.updated_ts_ms) < cutoff]
        for sid in stale_ids:
            row = self._sessions.pop(sid, None)
            if row is not None and self._latest_session_by_device.get(row.device_id) == sid:
                self._latest_session_by_device.pop(row.device_id, None)


def _normalize_roi_dict(value: dict[str, Any] | None) -> dict[str, float]:
    out = {"x": 0.35, "y": 0.35, "w": 0.3, "h": 0.3}
    if not isinstance(value, dict):
        return out
    try:
        x = float(value.get("x", out["x"]))
        y = float(value.get("y", out["y"]))
        w = float(value.get("w", out["w"]))
        h = float(value.get("h", out["h"]))
    except Exception:
        return out

    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.05, min(1.0, w))
    h = max(0.05, min(1.0, h))
    if x + w > 1.0:
        x = max(0.0, 1.0 - w)
    if y + h > 1.0:
        y = max(0.0, 1.0 - h)
    out.update({"x": x, "y": y, "w": w, "h": h})
    return out


def _normalize_tracker(value: str | None) -> str:
    token = str(value or "").strip().lower()
    if token not in {"botsort", "bytetrack"}:
        return "botsort"
    return token
