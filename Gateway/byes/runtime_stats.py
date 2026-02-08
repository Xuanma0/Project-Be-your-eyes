from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field


def _to_ms(value: float | int) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(numeric) or math.isinf(numeric):
        return 0.0
    return max(0.0, numeric)


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    q_clamped = max(0.0, min(1.0, float(q)))
    sorted_values = sorted(values)
    pos = q_clamped * (len(sorted_values) - 1)
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return sorted_values[lower]
    fraction = pos - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


@dataclass
class _ToolLatencyState:
    ema_queue_ms: float = 0.0
    ema_exec_ms: float = 0.0
    has_ema: bool = False
    queue_window_ms: deque[float] = field(default_factory=deque)
    exec_window_ms: deque[float] = field(default_factory=deque)


class RuntimeStats:
    """In-memory low-overhead runtime latencies for planner adaptation."""

    def __init__(self, window_size: int = 50, ema_alpha: float = 0.2) -> None:
        self._window_size = max(5, int(window_size))
        self._alpha = max(0.01, min(1.0, float(ema_alpha)))
        self._by_tool: dict[str, _ToolLatencyState] = {}

    def observe(self, tool: str, lane: str, queue_ms: float | int, exec_ms: float | int) -> None:
        _ = lane
        tool_key = str(tool or "").strip().lower()
        if not tool_key:
            return
        state = self._by_tool.get(tool_key)
        if state is None:
            state = _ToolLatencyState(
                queue_window_ms=deque(maxlen=self._window_size),
                exec_window_ms=deque(maxlen=self._window_size),
            )
            self._by_tool[tool_key] = state

        queue = _to_ms(queue_ms)
        exec_time = _to_ms(exec_ms)
        if not state.has_ema:
            state.ema_queue_ms = queue
            state.ema_exec_ms = exec_time
            state.has_ema = True
        else:
            state.ema_queue_ms = self._alpha * queue + (1.0 - self._alpha) * state.ema_queue_ms
            state.ema_exec_ms = self._alpha * exec_time + (1.0 - self._alpha) * state.ema_exec_ms

        state.queue_window_ms.append(queue)
        state.exec_window_ms.append(exec_time)

    def predict_total_ms(self, tool: str, *, quantile: str = "p95") -> float | None:
        tool_key = str(tool or "").strip().lower()
        if not tool_key:
            return None
        state = self._by_tool.get(tool_key)
        if state is None:
            return None

        q = 0.95
        if str(quantile).strip().lower() in {"p50", "median"}:
            q = 0.50

        if state.queue_window_ms and state.exec_window_ms:
            queue_est = _quantile(list(state.queue_window_ms), q)
            exec_est = _quantile(list(state.exec_window_ms), q)
        elif state.has_ema:
            queue_est = state.ema_queue_ms
            exec_est = state.ema_exec_ms
        else:
            return None
        return max(0.0, float(queue_est + exec_est))

    def snapshot(self, tool: str) -> dict[str, float] | None:
        tool_key = str(tool or "").strip().lower()
        state = self._by_tool.get(tool_key)
        if state is None:
            return None
        return {
            "ema_queue_ms": state.ema_queue_ms,
            "ema_exec_ms": state.ema_exec_ms,
            "p50_queue_ms": _quantile(list(state.queue_window_ms), 0.50) if state.queue_window_ms else 0.0,
            "p50_exec_ms": _quantile(list(state.exec_window_ms), 0.50) if state.exec_window_ms else 0.0,
            "p95_queue_ms": _quantile(list(state.queue_window_ms), 0.95) if state.queue_window_ms else 0.0,
            "p95_exec_ms": _quantile(list(state.exec_window_ms), 0.95) if state.exec_window_ms else 0.0,
        }

    def reset_runtime(self) -> None:
        self._by_tool.clear()
