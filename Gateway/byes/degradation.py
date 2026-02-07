from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

from byes.config import GatewayConfig
from byes.schema import ToolResult, ToolStatus


class DegradationState(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    SAFE_MODE = "SAFE_MODE"


@dataclass(frozen=True)
class StateChange:
    previous: DegradationState
    current: DegradationState
    reason: str


class DegradationManager:
    def __init__(self, config: GatewayConfig, metrics: object | None = None) -> None:
        self._config = config
        self._metrics = metrics
        self._state = DegradationState.NORMAL
        self._timeout_window: deque[bool] = deque(maxlen=max(1, config.timeout_window_size))
        self._ws_client_count = 0
        self._pending_changes: deque[StateChange] = deque()
        self._slow_backpressure_hits = 0

    @property
    def state(self) -> DegradationState:
        return self._state

    def is_degraded(self) -> bool:
        return self._state in {DegradationState.DEGRADED, DegradationState.SAFE_MODE}

    def is_safe_mode(self) -> bool:
        return self._state == DegradationState.SAFE_MODE

    def set_ws_client_count(self, count: int) -> None:
        self._ws_client_count = max(0, count)
        self._recompute("ws")

    def note_backpressure(self, lane: str) -> None:
        if lane == "slow":
            self._slow_backpressure_hits += 1
            self._recompute("slow_backpressure")

    def record_timeout(self, tool_name: str) -> None:
        _ = tool_name
        self._timeout_window.append(True)
        self._recompute("tool_timeout")

    def record_tool_result(self, result: ToolResult) -> None:
        self._timeout_window.append(result.status == ToolStatus.TIMEOUT)
        self._recompute("tool_result")

    def consume_state_changes(self) -> list[StateChange]:
        changes = list(self._pending_changes)
        self._pending_changes.clear()
        return changes

    def _recompute(self, reason: str) -> None:
        timeout_rate = self._timeout_rate()
        target = DegradationState.NORMAL

        if self._config.safe_mode_without_ws_client and self._ws_client_count == 0:
            target = DegradationState.SAFE_MODE
        elif timeout_rate >= self._config.timeout_rate_threshold * 1.5:
            target = DegradationState.SAFE_MODE
        elif timeout_rate >= self._config.timeout_rate_threshold or self._slow_backpressure_hits > 0:
            target = DegradationState.DEGRADED

        if target == self._state:
            return

        previous = self._state
        self._state = target
        self._pending_changes.append(StateChange(previous=previous, current=target, reason=reason))

        if target == DegradationState.SAFE_MODE and self._metrics is not None:
            fn = getattr(self._metrics, "inc_safemode_enter", None)
            if callable(fn):
                fn()

        if target == DegradationState.NORMAL:
            self._slow_backpressure_hits = 0

    def _timeout_rate(self) -> float:
        if not self._timeout_window:
            return 0.0
        timeout_count = sum(1 for item in self._timeout_window if item)
        return timeout_count / len(self._timeout_window)
