from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable


@dataclass
class _FrameRecord:
    received_at_ms: int
    ttl_ms: int
    deadline_ms: int
    completed: bool = False
    completed_ms: int | None = None
    outcome: str | None = None


class FrameTracker:
    """Tracks frame lifecycle and guarantees one completion accounting per seq."""

    def __init__(
        self,
        metrics: object | None = None,
        retention_ms: int = 120000,
        max_entries: int = 20000,
        now_ms_fn: Callable[[], int] | None = None,
    ) -> None:
        self._metrics = metrics
        self._retention_ms = max(1000, retention_ms)
        self._max_entries = max(100, max_entries)
        self._now_ms_fn = now_ms_fn or (lambda: int(time.time() * 1000))
        self._records: OrderedDict[int, _FrameRecord] = OrderedDict()

    def start_frame(self, seq: int, received_at_ms: int, ttl_ms: int) -> None:
        now_ms = self._now_ms_fn()
        self._cleanup(now_ms)
        normalized_ttl_ms = max(1, int(ttl_ms))
        normalized_received_at_ms = int(received_at_ms)
        deadline_ms = normalized_received_at_ms + normalized_ttl_ms

        record = self._records.get(seq)
        if record is None:
            self._records[seq] = _FrameRecord(
                received_at_ms=normalized_received_at_ms,
                ttl_ms=normalized_ttl_ms,
                deadline_ms=deadline_ms,
            )
            self._records.move_to_end(seq)
            self._metric_call("inc_frame_received")
            self._enforce_capacity()
            return

        # Existing record: keep earliest start/deadline and preserve completion state.
        record.received_at_ms = min(record.received_at_ms, normalized_received_at_ms)
        record.ttl_ms = min(record.ttl_ms, normalized_ttl_ms)
        record.deadline_ms = min(record.deadline_ms, deadline_ms)
        self._records.move_to_end(seq)

    def complete_frame(self, seq: int, outcome: str, completed_at_ms: int) -> bool:
        now_ms = int(completed_at_ms)
        self._cleanup(now_ms)

        record = self._records.get(seq)
        if record is None:
            record = _FrameRecord(
                received_at_ms=now_ms,
                ttl_ms=1,
                deadline_ms=now_ms + 1,
            )
            self._records[seq] = record

        if record.completed:
            return False

        record.completed = True
        record.completed_ms = now_ms
        record.outcome = outcome
        self._records.move_to_end(seq)

        latency_ms = max(0, now_ms - record.received_at_ms)
        self._metric_call("observe_e2e_latency", latency_ms)
        self._metric_call("inc_frame_completed", outcome)
        self._enforce_capacity()
        return True

    def reset_runtime(self) -> None:
        """Dev-only runtime reset. Metrics counters are intentionally untouched."""
        self._records.clear()

    @property
    def record_count(self) -> int:
        return len(self._records)

    def _cleanup(self, now_ms: int) -> None:
        stale_keys: list[int] = []
        for seq, record in self._records.items():
            if record.completed and record.completed_ms is not None:
                reference_ms = record.completed_ms
            else:
                reference_ms = max(record.received_at_ms, record.deadline_ms)
            if now_ms - reference_ms > self._retention_ms:
                stale_keys.append(seq)
            else:
                break

        for seq in stale_keys:
            self._records.pop(seq, None)

    def _enforce_capacity(self) -> None:
        while len(self._records) > self._max_entries:
            self._records.popitem(last=False)

    def _metric_call(self, method: str, *args: object) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)
