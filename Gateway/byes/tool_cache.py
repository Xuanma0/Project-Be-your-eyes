from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from byes.schema import ToolResult


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class ToolCacheEntry:
    tool_result: ToolResult
    produced_events: list[dict[str, Any]]
    produced_at_ms: int
    fingerprint: str


class ToolCache:
    """Small in-memory cache keyed by (tool_name, cache_key)."""

    def __init__(self, max_entries: int = 1024) -> None:
        self._max_entries = max(64, int(max_entries))
        self._entries: dict[tuple[str, str], ToolCacheEntry] = {}

    def get(
        self,
        tool_name: str,
        cache_key: str,
        now_ms: int | None,
        max_age_ms: int,
        fingerprint: str,
    ) -> ToolCacheEntry | None:
        if not cache_key or max_age_ms <= 0:
            return None
        key = (tool_name, cache_key)
        entry = self._entries.get(key)
        if entry is None:
            return None
        current_ms = now_ms if now_ms is not None else _now_ms()
        if current_ms - entry.produced_at_ms > max_age_ms:
            self._entries.pop(key, None)
            return None
        if fingerprint and entry.fingerprint and fingerprint != entry.fingerprint:
            return None
        return entry

    def set(
        self,
        tool_name: str,
        cache_key: str,
        tool_result: ToolResult,
        produced_events: list[dict[str, Any]] | None,
        produced_at_ms: int | None,
        fingerprint: str,
    ) -> None:
        if not cache_key:
            return
        key = (tool_name, cache_key)
        entry = ToolCacheEntry(
            tool_result=tool_result.model_copy(deep=True),
            produced_events=list(produced_events or []),
            produced_at_ms=produced_at_ms if produced_at_ms is not None else _now_ms(),
            fingerprint=fingerprint,
        )
        self._entries[key] = entry
        if len(self._entries) > self._max_entries:
            oldest_key = next(iter(self._entries.keys()))
            self._entries.pop(oldest_key, None)

    def reset_runtime(self) -> None:
        self._entries.clear()
