from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class CachedAsset:
    asset_id: str
    content_type: str
    data: bytes
    created_ts_ms: int
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def age_ms(self) -> int:
        return max(0, _now_ms() - int(self.created_ts_ms))


class AssetCache:
    def __init__(self, *, ttl_ms: int = 12000, max_entries: int = 256, max_total_bytes: int = 32 * 1024 * 1024) -> None:
        self._ttl_ms = max(1000, int(ttl_ms))
        self._max_entries = max(1, int(max_entries))
        self._max_total_bytes = max(1024, int(max_total_bytes))
        self._entries: OrderedDict[str, CachedAsset] = OrderedDict()
        self._total_bytes = 0

    def reset(self) -> None:
        self._entries.clear()
        self._total_bytes = 0

    def put(
        self,
        *,
        data: bytes,
        content_type: str = "application/octet-stream",
        meta: dict[str, Any] | None = None,
        preferred_id: str | None = None,
    ) -> CachedAsset:
        payload = bytes(data or b"")
        now_ms = _now_ms()
        self._purge_expired(now_ms)
        digest = hashlib.sha1(payload).hexdigest()[:16]
        base_id = str(preferred_id or "").strip() or f"a_{now_ms}_{digest}"
        asset_id = base_id
        suffix = 1
        while asset_id in self._entries:
            existing = self._entries[asset_id]
            if existing.data == payload and existing.content_type == str(content_type or "application/octet-stream"):
                existing.created_ts_ms = now_ms
                existing.meta = dict(meta or existing.meta or {})
                self._entries.move_to_end(asset_id, last=True)
                return existing
            asset_id = f"{base_id}_{suffix}"
            suffix += 1

        record = CachedAsset(
            asset_id=asset_id,
            content_type=str(content_type or "application/octet-stream").strip() or "application/octet-stream",
            data=payload,
            created_ts_ms=now_ms,
            meta=dict(meta or {}),
        )
        self._entries[asset_id] = record
        self._entries.move_to_end(asset_id, last=True)
        self._total_bytes += len(payload)
        self._enforce_limits()
        return record

    def get(self, asset_id: str, *, max_age_ms: int | None = None) -> CachedAsset | None:
        now_ms = _now_ms()
        self._purge_expired(now_ms)
        key = str(asset_id or "").strip()
        if not key:
            return None
        record = self._entries.get(key)
        if record is None:
            return None
        effective_max_age = self._ttl_ms if max_age_ms is None else max(1, int(max_age_ms))
        if max(0, now_ms - int(record.created_ts_ms)) > effective_max_age:
            self._pop_key(key)
            return None
        self._entries.move_to_end(key, last=True)
        return record

    def get_meta(self, asset_id: str) -> dict[str, Any] | None:
        record = self.get(asset_id)
        if record is None:
            return None
        width = None
        height = None
        try:
            width = int(record.meta.get("w")) if isinstance(record.meta, dict) and record.meta.get("w") is not None else None
            height = int(record.meta.get("h")) if isinstance(record.meta, dict) and record.meta.get("h") is not None else None
        except Exception:
            width = None
            height = None
        expires_ts_ms = int(record.created_ts_ms) + int(self._ttl_ms)
        return {
            "assetId": record.asset_id,
            "contentType": record.content_type,
            "sizeBytes": int(record.size_bytes),
            "createdTsMs": int(record.created_ts_ms),
            "expiresTsMs": int(expires_ts_ms),
            "width": width,
            "height": height,
            "ageMs": int(record.age_ms),
            "meta": dict(record.meta or {}),
        }

    def _enforce_limits(self) -> None:
        while len(self._entries) > self._max_entries:
            self._pop_oldest()
        while self._total_bytes > self._max_total_bytes and self._entries:
            self._pop_oldest()

    def _purge_expired(self, now_ms: int) -> None:
        cutoff = now_ms - self._ttl_ms
        stale_keys = [key for key, row in self._entries.items() if int(row.created_ts_ms) < cutoff]
        for key in stale_keys:
            self._pop_key(key)

    def _pop_oldest(self) -> None:
        key, row = self._entries.popitem(last=False)
        self._total_bytes = max(0, self._total_bytes - len(row.data))

    def _pop_key(self, key: str) -> None:
        row = self._entries.pop(key, None)
        if row is None:
            return
        self._total_bytes = max(0, self._total_bytes - len(row.data))
