from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class CachedFrame:
    device_id: str
    frame_seq: int
    stored_ts_ms: int
    frame_bytes: bytes
    meta: dict[str, Any]
    run_id: str
    capture_ts_ms: int | None = None

    @property
    def age_ms(self) -> int:
        return max(0, _now_ms() - int(self.stored_ts_ms))


class FrameCache:
    def __init__(self, *, ttl_ms: int = 2000, max_entries: int = 16) -> None:
        self._ttl_ms = max(1, int(ttl_ms))
        self._max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[str, CachedFrame] = OrderedDict()

    def reset(self) -> None:
        self._entries.clear()

    def set(
        self,
        *,
        device_id: str,
        frame_seq: int,
        frame_bytes: bytes,
        meta: dict[str, Any],
        run_id: str,
        capture_ts_ms: int | None = None,
    ) -> CachedFrame:
        now_ms = _now_ms()
        self._purge_expired(now_ms)
        normalized_device = str(device_id or "default").strip() or "default"
        cached = CachedFrame(
            device_id=normalized_device,
            frame_seq=max(1, int(frame_seq)),
            stored_ts_ms=now_ms,
            frame_bytes=bytes(frame_bytes or b""),
            meta=dict(meta or {}),
            run_id=str(run_id or "").strip() or "unknown-run",
            capture_ts_ms=int(capture_ts_ms) if capture_ts_ms is not None else None,
        )
        self._entries[normalized_device] = cached
        self._entries.move_to_end(normalized_device, last=True)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return cached

    def get(self, *, device_id: str, max_age_ms: int | None = None) -> CachedFrame | None:
        now_ms = _now_ms()
        self._purge_expired(now_ms)
        normalized_device = str(device_id or "default").strip() or "default"
        item = self._entries.get(normalized_device)
        if item is None:
            return None
        age_ms = max(0, now_ms - int(item.stored_ts_ms))
        effective_max_age = self._ttl_ms if max_age_ms is None else max(1, int(max_age_ms))
        if age_ms > effective_max_age:
            self._entries.pop(normalized_device, None)
            return None
        self._entries.move_to_end(normalized_device, last=True)
        return item

    def _purge_expired(self, now_ms: int) -> None:
        cutoff = now_ms - self._ttl_ms
        stale = [key for key, row in self._entries.items() if int(row.stored_ts_ms) < cutoff]
        for key in stale:
            self._entries.pop(key, None)
