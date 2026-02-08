from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from byes.config import GatewayConfig
from byes.tools.base import BaseTool


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class FrameContext:
    seq: int
    received_at_ms: int
    ttl_ms: int
    intent: str
    frame_fingerprint: str
    safe_mode: bool
    degraded: bool
    meta: dict[str, Any]


@dataclass(frozen=True)
class GateDecision:
    run: bool
    reason: str
    reuse_ok: bool
    min_interval_ms: int
    max_age_ms: int


class FrameGate:
    """Applies tool-level gating decisions with fixed, low-cardinality reasons."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._last_run_ms_by_tool: dict[str, int] = {}
        self._last_fingerprint_by_tool: dict[str, str] = {}

    def decide(self, tool: BaseTool, frame: FrameContext, now_ms: int | None = None) -> GateDecision:
        current_ms = now_ms if now_ms is not None else _now_ms()
        intent = frame.intent.strip().lower()

        if frame.safe_mode and tool.capability != "risk":
            return GateDecision(
                run=False,
                reason="safe_mode",
                reuse_ok=False,
                min_interval_ms=0,
                max_age_ms=0,
            )

        if frame.ttl_ms <= 0:
            return GateDecision(
                run=False,
                reason="ttl_risk",
                reuse_ok=False,
                min_interval_ms=0,
                max_age_ms=0,
            )

        if tool.name == "real_ocr":
            if intent != "scan_text":
                return GateDecision(
                    run=False,
                    reason="intent_off",
                    reuse_ok=False,
                    min_interval_ms=0,
                    max_age_ms=0,
                )
            return GateDecision(
                run=True,
                reason="policy",
                reuse_ok=True,
                min_interval_ms=max(0, int(self._config.real_ocr_min_interval_ms)),
                max_age_ms=max(0, int(self._config.real_ocr_cache_max_age_ms)),
            )

        if tool.name == "real_det":
            min_interval_ms = max(0, int(self._config.real_det_min_interval_ms))
            max_age_ms = max(0, int(self._config.real_det_cache_max_age_ms))
            last_run_ms = self._last_run_ms_by_tool.get(tool.name, -1)
            last_fingerprint = self._last_fingerprint_by_tool.get(tool.name, "")
            unchanged = (
                bool(frame.frame_fingerprint)
                and bool(last_fingerprint)
                and frame.frame_fingerprint == last_fingerprint
            )
            within_interval = (
                last_run_ms >= 0
                and min_interval_ms > 0
                and (current_ms - last_run_ms) < min_interval_ms
            )

            if unchanged and max_age_ms > 0 and (current_ms - last_run_ms) <= max_age_ms:
                return GateDecision(
                    run=False,
                    reason="unchanged",
                    reuse_ok=True,
                    min_interval_ms=min_interval_ms,
                    max_age_ms=max_age_ms,
                )

            if within_interval and not unchanged:
                # Scene changed: allow immediate det update.
                return GateDecision(
                    run=True,
                    reason="policy",
                    reuse_ok=True,
                    min_interval_ms=min_interval_ms,
                    max_age_ms=max_age_ms,
                )

            if within_interval:
                return GateDecision(
                    run=False,
                    reason="rate_limit",
                    reuse_ok=True,
                    min_interval_ms=min_interval_ms,
                    max_age_ms=max_age_ms,
                )

            return GateDecision(
                run=True,
                reason="policy",
                reuse_ok=True,
                min_interval_ms=min_interval_ms,
                max_age_ms=max_age_ms,
            )

        return GateDecision(
            run=True,
            reason="policy",
            reuse_ok=False,
            min_interval_ms=0,
            max_age_ms=0,
        )

    def record_run(self, tool_name: str, frame_fingerprint: str, now_ms: int | None = None) -> None:
        current_ms = now_ms if now_ms is not None else _now_ms()
        self._last_run_ms_by_tool[tool_name] = current_ms
        if frame_fingerprint:
            self._last_fingerprint_by_tool[tool_name] = frame_fingerprint

    def reset_runtime(self) -> None:
        self._last_run_ms_by_tool.clear()
        self._last_fingerprint_by_tool.clear()
