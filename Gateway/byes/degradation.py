from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable

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


@dataclass(frozen=True)
class HealthAlert:
    status: str
    reason: str


class DegradationManager:
    def __init__(
        self,
        config: GatewayConfig,
        metrics: object | None = None,
        now_ms_fn: Callable[[], int] | None = None,
    ) -> None:
        self._config = config
        self._metrics = metrics
        self._now_ms_fn = now_ms_fn or (lambda: int(time.time() * 1000))

        self._state = DegradationState.NORMAL
        self._timeout_window: deque[bool] = deque(maxlen=max(1, config.timeout_window_size))
        self._ws_client_count = 0
        self._had_client_ever_connected = False
        self._disconnect_since_ms: int | None = None
        self._last_warn_ms = -1

        self._pending_changes: deque[StateChange] = deque()
        self._pending_alerts: deque[HealthAlert] = deque()

        self._slow_backpressure_hits = 0
        self._unavailable_hits = 0

    @property
    def state(self) -> DegradationState:
        return self._state

    @property
    def had_client_ever_connected(self) -> bool:
        return self._had_client_ever_connected

    def is_degraded(self) -> bool:
        return self._state in {DegradationState.DEGRADED, DegradationState.SAFE_MODE}

    def is_safe_mode(self) -> bool:
        return self._state == DegradationState.SAFE_MODE

    def set_ws_client_count(self, count: int) -> None:
        now_ms = self._now_ms_fn()
        previous_count = self._ws_client_count
        self._ws_client_count = max(0, count)

        if self._ws_client_count > 0:
            self._had_client_ever_connected = True
            self._disconnect_since_ms = None
        elif previous_count > 0 and self._had_client_ever_connected:
            self._disconnect_since_ms = now_ms

        self._recompute("ws", now_ms)

    def tick(self) -> None:
        self._recompute("tick", self._now_ms_fn())

    def note_backpressure(self, lane: str) -> None:
        if lane == "slow":
            self._slow_backpressure_hits += 1
            self._recompute("slow_backpressure", self._now_ms_fn())

    def record_timeout(self, tool_name: str) -> None:
        _ = tool_name
        self._timeout_window.append(True)
        self._recompute("tool_timeout", self._now_ms_fn())

    def record_unavailable(self, tool_name: str) -> None:
        _ = tool_name
        self._unavailable_hits += 1
        self._recompute("tool_unavailable", self._now_ms_fn())

    def record_tool_result(self, result: ToolResult) -> None:
        self._timeout_window.append(result.status == ToolStatus.TIMEOUT)
        if result.status == ToolStatus.ERROR and result.error == "unavailable":
            self._unavailable_hits += 1
        self._recompute("tool_result", self._now_ms_fn())

    def consume_state_changes(self) -> list[StateChange]:
        changes = list(self._pending_changes)
        self._pending_changes.clear()
        return changes

    def consume_alerts(self) -> list[HealthAlert]:
        alerts = list(self._pending_alerts)
        self._pending_alerts.clear()
        return alerts

    def reset_runtime(self) -> None:
        """Dev-only runtime reset. Metrics counters are intentionally untouched."""
        self._state = DegradationState.NORMAL
        self._timeout_window.clear()
        self._ws_client_count = 0
        self._had_client_ever_connected = False
        self._disconnect_since_ms = None
        self._last_warn_ms = -1
        self._pending_changes.clear()
        self._pending_alerts.clear()
        self._slow_backpressure_hits = 0
        self._unavailable_hits = 0

    def _recompute(self, reason: str, now_ms: int) -> None:
        timeout_rate = self._timeout_rate()
        target = DegradationState.NORMAL

        if timeout_rate >= self._config.timeout_rate_threshold * 1.5:
            target = DegradationState.SAFE_MODE
        elif timeout_rate >= self._config.timeout_rate_threshold or self._slow_backpressure_hits > 0 or self._unavailable_hits > 0:
            target = DegradationState.DEGRADED

        ws_disconnect_active = self._ws_disconnect_active(now_ms)
        if self._config.safe_mode_without_ws_client and ws_disconnect_active:
            if timeout_rate >= self._config.timeout_rate_threshold:
                target = DegradationState.SAFE_MODE
            elif target == DegradationState.NORMAL:
                target = DegradationState.DEGRADED

        if not self._had_client_ever_connected and self._ws_client_count == 0:
            self._maybe_emit_waiting_client_warn(now_ms)

        if target != self._state:
            previous = self._state
            self._state = target
            change = StateChange(previous=previous, current=target, reason=reason)
            self._pending_changes.append(change)
            self._metric_call("inc_degradation_state_change", previous.value, target.value, reason)
            if target == DegradationState.SAFE_MODE:
                self._metric_call("inc_safemode_enter")

        if target == DegradationState.NORMAL:
            self._slow_backpressure_hits = 0
            self._unavailable_hits = 0

    def _ws_disconnect_active(self, now_ms: int) -> bool:
        if not self._had_client_ever_connected:
            return False
        if self._ws_client_count > 0:
            return False
        if self._disconnect_since_ms is None:
            return False
        return now_ms - self._disconnect_since_ms >= self._config.ws_disconnect_grace_ms

    def _maybe_emit_waiting_client_warn(self, now_ms: int) -> None:
        if self._last_warn_ms >= 0 and now_ms - self._last_warn_ms < self._config.ws_no_client_warn_interval_ms:
            return
        self._last_warn_ms = now_ms
        self._pending_alerts.append(HealthAlert(status="gateway_waiting_client", reason="no_ws_client_yet"))
        self._metric_call("inc_health_warn", "gateway_waiting_client")

    def _timeout_rate(self) -> float:
        if not self._timeout_window:
            return 0.0
        timeout_count = sum(1 for item in self._timeout_window if item)
        return timeout_count / len(self._timeout_window)

    def _metric_call(self, method: str, *args: object) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)
