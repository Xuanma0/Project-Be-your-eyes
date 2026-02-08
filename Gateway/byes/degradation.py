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
        self._configured_critical_tools = {
            item.strip().lower()
            for item in str(config.critical_tools_csv).split(",")
            if item.strip()
        }
        self._configured_critical_tools.add("mock_risk")
        self._enabled_tools = {
            item.strip().lower()
            for item in str(config.enabled_tools_csv).split(",")
            if item.strip()
        }
        self._registry_tools: set[str] = set()
        self._effective_critical_tools: set[str] = set()
        self._missing_critical_tools: set[str] = set()

        self._state = DegradationState.NORMAL
        self._timeout_window: deque[bool] = deque(maxlen=max(1, config.timeout_window_size))
        self._critical_fault_active = False
        self._noncritical_fault_active = False
        self._ws_client_count = 0
        self._had_client_ever_connected = False
        self._disconnect_since_ms: int | None = None
        self._last_warn_ms = -1

        self._pending_changes: deque[StateChange] = deque()
        self._pending_alerts: deque[HealthAlert] = deque()
        self._current_reason = "tool_result:init"

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

    def timeout_rate(self) -> float:
        return self._timeout_rate()

    def set_ws_client_count(self, count: int) -> None:
        now_ms = self._now_ms_fn()
        previous_count = self._ws_client_count
        self._ws_client_count = max(0, count)

        if self._ws_client_count > 0:
            self._had_client_ever_connected = True
            self._disconnect_since_ms = None
        elif previous_count > 0 and self._had_client_ever_connected:
            self._disconnect_since_ms = now_ms

        self._recompute("tool_result:ws", now_ms)

    def tick(self) -> None:
        self._recompute("tick", self._now_ms_fn())

    def note_backpressure(self, lane: str) -> None:
        if lane == "slow":
            self._slow_backpressure_hits += 1
            self._recompute(f"rate_limit:{lane}", self._now_ms_fn())

    def record_timeout(self, tool_name: str) -> None:
        tool = str(tool_name).strip().lower()
        self._timeout_window.append(True)
        if self._is_critical_tool(tool):
            self._critical_fault_active = True
            reason = f"critical_timeout:{tool}"
        else:
            self._noncritical_fault_active = True
            reason = f"noncritical_timeout:{tool}"
        self._recompute(reason, self._now_ms_fn())

    def record_unavailable(self, tool_name: str) -> None:
        tool = str(tool_name).strip().lower()
        self._unavailable_hits += 1
        if self._is_critical_tool(tool):
            self._critical_fault_active = True
            reason = f"critical_unavailable:{tool}"
        else:
            self._noncritical_fault_active = True
            reason = f"noncritical_unavailable:{tool}"
        self._recompute(reason, self._now_ms_fn())

    def record_tool_result(self, result: ToolResult) -> None:
        tool = str(result.toolName).strip().lower()
        if result.status == ToolStatus.TIMEOUT:
            # Timeout is handled in `record_timeout` to avoid duplicate accounting.
            return

        self._timeout_window.append(False)

        if result.status == ToolStatus.ERROR and result.error == "unavailable":
            # Unavailable is handled in `record_unavailable`.
            return

        if self._is_critical_tool(tool):
            if result.status == ToolStatus.OK:
                self._critical_fault_active = False
                reason = f"tool_result:{tool}"
            elif result.status == ToolStatus.ERROR:
                self._critical_fault_active = True
                reason = f"critical_error:{tool}"
            else:
                reason = f"tool_result:{tool}"
        else:
            if result.status == ToolStatus.OK:
                self._noncritical_fault_active = False
                reason = f"tool_result:{tool}"
            elif result.status == ToolStatus.ERROR:
                self._unavailable_hits += 1
                self._noncritical_fault_active = True
                reason = f"noncritical_error:{tool}"
            else:
                reason = f"tool_result:{tool}"
        self._recompute(reason, self._now_ms_fn())

    def set_tool_inventory(self, registry_tools: set[str] | list[str], enabled_tools: set[str] | list[str] | None = None) -> None:
        self._registry_tools = {str(item).strip().lower() for item in registry_tools if str(item).strip()}
        if enabled_tools is not None:
            self._enabled_tools = {str(item).strip().lower() for item in enabled_tools if str(item).strip()}
        self._refresh_effective_critical()
        self._recompute("tool_result:inventory", self._now_ms_fn())

    def get_health(self, status_only: bool = False) -> tuple[str, str]:
        if not self._had_client_ever_connected and self._ws_client_count == 0:
            if status_only:
                return "WAITING_CLIENT", ""
            return "WAITING_CLIENT", "waiting_client"
        status = self._state.value
        if status_only:
            return status, ""
        return status, self._current_reason

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
        self._critical_fault_active = False
        self._noncritical_fault_active = False
        self._current_reason = "tool_result:reset"
        self._ws_client_count = 0
        self._had_client_ever_connected = False
        self._disconnect_since_ms = None
        self._last_warn_ms = -1
        self._pending_changes.clear()
        self._pending_alerts.clear()
        self._slow_backpressure_hits = 0
        self._unavailable_hits = 0

    def _recompute(self, reason: str, now_ms: int) -> None:
        self._refresh_effective_critical()
        timeout_rate = self._timeout_rate()
        target = DegradationState.NORMAL

        if self._missing_critical_tools:
            target = DegradationState.SAFE_MODE
            reason = f"critical_missing:{sorted(self._missing_critical_tools)[0]}"
        elif self._critical_fault_active:
            target = DegradationState.SAFE_MODE
        elif (
            self._noncritical_fault_active
            or timeout_rate >= self._config.timeout_rate_threshold
            or self._slow_backpressure_hits > 0
            or self._unavailable_hits > 0
        ):
            target = DegradationState.DEGRADED

        ws_disconnect_active = self._ws_disconnect_active(now_ms)
        if self._config.safe_mode_without_ws_client and ws_disconnect_active:
            if target == DegradationState.NORMAL:
                target = DegradationState.DEGRADED
                reason = "ws_disconnect"

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
            self._current_reason = reason
        elif target != DegradationState.NORMAL:
            self._current_reason = reason

        if target == DegradationState.NORMAL:
            self._slow_backpressure_hits = 0
            self._unavailable_hits = 0
            self._critical_fault_active = False
            self._noncritical_fault_active = False
            self._current_reason = "tool_result:normal"

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
        self._pending_alerts.append(HealthAlert(status="gateway_waiting_client", reason="waiting_client"))
        self._metric_call("inc_health_warn", "gateway_waiting_client")

    def _timeout_rate(self) -> float:
        if not self._timeout_window:
            return 0.0
        timeout_count = sum(1 for item in self._timeout_window if item)
        return timeout_count / len(self._timeout_window)

    def _is_critical_tool(self, tool_name: str) -> bool:
        return str(tool_name).strip().lower() in self._effective_critical_tools

    def _refresh_effective_critical(self) -> None:
        if not self._registry_tools:
            base_enabled = self._enabled_tools if self._enabled_tools else self._configured_critical_tools
            self._effective_critical_tools = self._configured_critical_tools.intersection(base_enabled)
            self._missing_critical_tools = set()
            return

        enabled_scope = self._enabled_tools if self._enabled_tools else set(self._registry_tools)
        candidates = self._configured_critical_tools.intersection(enabled_scope)
        self._effective_critical_tools = candidates.intersection(self._registry_tools)
        self._missing_critical_tools = candidates.difference(self._registry_tools)

    def _metric_call(self, method: str, *args: object) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)
