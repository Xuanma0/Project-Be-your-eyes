from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from byes.preprocess import FrameArtifacts, FramePreprocessor


@dataclass
class _FrameRecord:
    received_at_ms: int
    ttl_ms: int
    deadline_ms: int
    frame_meta: Any | None = None
    artifacts: FrameArtifacts | None = None
    received_counted: bool = True
    completed: bool = False
    completed_ms: int | None = None
    outcome: str | None = None
    first_action_emitted_at_ms: int | None = None
    first_action_kind: str | None = None
    ttfa_hist_observed: bool = False
    ttfa_outcome_observed: bool = False
    ttfa_block_reason: str | None = None
    ttfa_block_kind: str = "none"


class FrameTracker:
    """Tracks frame lifecycle and guarantees one completion accounting per seq."""

    def __init__(
        self,
        metrics: object | None = None,
        retention_ms: int = 120000,
        max_entries: int = 20000,
        now_ms_fn: Callable[[], int] | None = None,
        governor: object | None = None,
    ) -> None:
        self._metrics = metrics
        self._retention_ms = max(1000, retention_ms)
        self._max_entries = max(100, max_entries)
        self._now_ms_fn = now_ms_fn or (lambda: int(time.time() * 1000))
        self._governor = governor
        self._records: OrderedDict[int, _FrameRecord] = OrderedDict()

    def start_frame(self, seq: int, received_at_ms: int, ttl_ms: int, frame_meta: Any | None = None) -> None:
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
                frame_meta=frame_meta,
                received_counted=True,
            )
            self._records.move_to_end(seq)
            self._metric_call("inc_frame_received")
            self._enforce_capacity()
            return

        # Existing record: keep earliest start/deadline and preserve completion state.
        record.received_at_ms = min(record.received_at_ms, normalized_received_at_ms)
        record.ttl_ms = min(record.ttl_ms, normalized_ttl_ms)
        record.deadline_ms = min(record.deadline_ms, deadline_ms)
        if record.frame_meta is None and frame_meta is not None:
            record.frame_meta = frame_meta
        if not record.received_counted:
            record.received_counted = True
            self._metric_call("inc_frame_received")
        self._records.move_to_end(seq)

    def get_or_build_artifacts(
        self,
        seq: int,
        frame_bytes: bytes,
        meta: dict[str, Any] | None,
        preprocessor: FramePreprocessor,
    ) -> FrameArtifacts:
        now_ms = self._now_ms_fn()
        self._cleanup(now_ms)
        record = self._records.get(seq)
        if record is None:
            ttl_ms = 1
            if isinstance(meta, dict):
                try:
                    ttl_ms = max(1, int(meta.get("ttlMs", 1)))
                except (TypeError, ValueError):
                    ttl_ms = 1
            record = _FrameRecord(
                received_at_ms=now_ms,
                ttl_ms=ttl_ms,
                deadline_ms=now_ms + ttl_ms,
                frame_meta=None,
                received_counted=False,
            )
            self._records[seq] = record
            self._records.move_to_end(seq)
        elif record.artifacts is not None:
            self._records.move_to_end(seq)
            self._metric_call("inc_preprocess_cache_hit")
            return record.artifacts

        frame_meta = record.frame_meta
        if frame_meta is None and isinstance(meta, dict):
            candidate = meta.get("frameMeta")
            if isinstance(candidate, dict):
                frame_meta = candidate
        artifacts = preprocessor.build(seq=seq, frame_bytes=frame_bytes, frame_meta=frame_meta)
        record.artifacts = artifacts
        self._records.move_to_end(seq)
        self._metric_call("observe_preprocess_latency", artifacts.build_latency_ms)
        self._metric_call("inc_preprocess_bytes", "full", len(artifacts.full_bytes))
        self._metric_call("inc_preprocess_bytes", "det", len(artifacts.det_jpeg_bytes))
        self._metric_call("inc_preprocess_bytes", "ocr", len(artifacts.ocr_jpeg_bytes))
        self._metric_call("inc_preprocess_bytes", "depth", len(artifacts.depth_jpeg_bytes))
        if artifacts.decode_error:
            self._metric_call("inc_preprocess_decode_error")
        self._governor_call("record_preprocess_ms", artifacts.build_latency_ms)
        self._enforce_capacity()
        return artifacts

    def complete_frame(self, seq: int, outcome: str, completed_at_ms: int) -> bool:
        now_ms = int(completed_at_ms)
        self._cleanup(now_ms)

        record = self._records.get(seq)
        if record is None:
            record = _FrameRecord(
                received_at_ms=now_ms,
                ttl_ms=1,
                deadline_ms=now_ms + 1,
                received_counted=False,
            )
            self._records[seq] = record

        if record.completed:
            return False

        record.completed = True
        record.completed_ms = now_ms
        record.outcome = outcome
        self._records.move_to_end(seq)

        self._observe_ttfa_outcome(record, outcome)
        latency_ms = max(0, now_ms - record.received_at_ms)
        self._metric_call("observe_e2e_latency", latency_ms)
        self._metric_call("inc_frame_completed", outcome)
        self._governor_call("record_e2e_ms", latency_ms)
        self._enforce_capacity()
        return True

    def mark_first_action(self, seq: int, emitted_at_ms: int, kind: str) -> bool:
        now_ms = int(emitted_at_ms)
        self._cleanup(now_ms)
        normalized_kind = self._normalize_ttfa_kind(kind)

        record = self._records.get(seq)
        if record is None:
            record = _FrameRecord(
                received_at_ms=now_ms,
                ttl_ms=1,
                deadline_ms=now_ms + 1,
                received_counted=False,
            )
            self._records[seq] = record

        if record.ttfa_hist_observed:
            return False

        record.first_action_emitted_at_ms = now_ms
        record.first_action_kind = normalized_kind
        record.ttfa_hist_observed = True
        self._records.move_to_end(seq)

        ttfa_ms = max(0, now_ms - record.received_at_ms)
        self._metric_call("observe_ttfa", ttfa_ms)
        return True

    def note_ttfa_block(self, seq: int, reason: str, kind: str = "none") -> None:
        now_ms = self._now_ms_fn()
        self._cleanup(now_ms)
        record = self._records.get(seq)
        if record is None:
            record = _FrameRecord(
                received_at_ms=now_ms,
                ttl_ms=1,
                deadline_ms=now_ms + 1,
                received_counted=False,
            )
            self._records[seq] = record
        next_reason = self._normalize_ttfa_block_reason(reason)
        if record.ttfa_block_reason is None:
            record.ttfa_block_reason = next_reason
            record.ttfa_block_kind = self._normalize_ttfa_kind(kind, allow_none=True)
            return
        if self._ttfa_block_priority(next_reason) > self._ttfa_block_priority(record.ttfa_block_reason):
            record.ttfa_block_reason = next_reason
            record.ttfa_block_kind = self._normalize_ttfa_kind(kind, allow_none=True)

    def reset_runtime(self) -> None:
        """Dev-only runtime reset. Metrics counters are intentionally untouched."""
        self._records.clear()

    @property
    def record_count(self) -> int:
        return len(self._records)

    def get_frame_meta(self, seq: int) -> Any | None:
        record = self._records.get(seq)
        if record is None:
            return None
        return record.frame_meta

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

    def _governor_call(self, method: str, *args: object) -> None:
        if self._governor is None:
            return
        fn = getattr(self._governor, method, None)
        if callable(fn):
            fn(*args)

    def _observe_ttfa_outcome(self, record: _FrameRecord, outcome: str) -> None:
        if record.ttfa_outcome_observed:
            return
        if record.first_action_emitted_at_ms is not None:
            ttfa_outcome = "ok"
            ttfa_kind = record.first_action_kind or "risk"
        else:
            ttfa_outcome = self._map_ttfa_outcome(outcome, record.ttfa_block_reason)
            ttfa_kind = record.ttfa_block_kind or "none"
        self._metric_call("inc_ttfa_count", ttfa_outcome, ttfa_kind)
        self._metric_call("inc_ttfa_outcome", ttfa_outcome, ttfa_kind)
        record.ttfa_outcome_observed = True

    @staticmethod
    def _normalize_ttfa_kind(kind: str, allow_none: bool = False) -> str:
        normalized = str(kind).strip().lower()
        if normalized in {"risk", "action_plan"}:
            return normalized
        if allow_none:
            return "none"
        return "risk"

    @staticmethod
    def _normalize_ttfa_block_reason(reason: str) -> str:
        normalized = str(reason).strip().lower()
        if normalized.startswith("safe_mode"):
            return "blocked_safe_mode"
        if normalized.startswith("action_gate"):
            return "blocked_action_gate"
        if normalized.startswith("timeout_critical"):
            return "timeout_critical"
        if normalized.startswith("timeout_noncritical"):
            return "timeout_noncritical"
        if normalized in {"blocked_safe_mode", "blocked_action_gate", "timeout_critical", "timeout_noncritical"}:
            return normalized
        return "no_output"

    @staticmethod
    def _ttfa_block_priority(reason: str) -> int:
        table = {
            "blocked_safe_mode": 5,
            "blocked_action_gate": 4,
            "timeout_critical": 3,
            "timeout_noncritical": 2,
            "no_output": 1,
        }
        return table.get(reason, 0)

    @staticmethod
    def _map_ttfa_outcome(outcome: str, block_reason: str | None) -> str:
        if block_reason:
            return block_reason
        normalized = str(outcome).strip().lower()
        if normalized == "ttl_drop":
            return "ttl_drop"
        if normalized == "canceled":
            return "canceled"
        if normalized in {"error", "failed"}:
            return "error"
        if normalized in {"safemode_suppressed", "suppressed"}:
            return "blocked_safe_mode"
        if normalized == "ok":
            return "no_output"
        return "error"
