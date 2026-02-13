from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from byes.config import GatewayConfig


@dataclass(frozen=True)
class GovernorSnapshot:
    mode: str
    reason: str


class SloGovernor:
    """Lightweight SLO governor that only throttles scheduling decisions."""

    def __init__(self, config: GatewayConfig, metrics: object | None = None) -> None:
        self._config = config
        self._metrics = metrics
        self._mode = "NORMAL"
        self._reason = "normal"
        self._recover_ticks = 0
        window = max(5, int(config.slo_window_size))
        self._e2e_samples_ms: deque[float] = deque(maxlen=window)
        self._preproc_samples_ms: deque[float] = deque(maxlen=window)
        self._queue_depth_samples: deque[float] = deque(maxlen=window)
        self._timeout_rate_samples: deque[float] = deque(maxlen=window)
        self._set_mode_gauge(self._mode)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def reason(self) -> str:
        return self._reason

    def snapshot(self) -> GovernorSnapshot:
        return GovernorSnapshot(mode=self._mode, reason=self._reason)

    def reset_runtime(self) -> None:
        self._mode = "NORMAL"
        self._reason = "normal"
        self._recover_ticks = 0
        self._e2e_samples_ms.clear()
        self._preproc_samples_ms.clear()
        self._queue_depth_samples.clear()
        self._timeout_rate_samples.clear()
        self._set_mode_gauge(self._mode)

    def record_e2e_ms(self, latency_ms: int) -> None:
        self._e2e_samples_ms.append(float(max(0, int(latency_ms))))

    def record_preprocess_ms(self, latency_ms: int) -> None:
        self._preproc_samples_ms.append(float(max(0, int(latency_ms))))

    def tick(self, *, queue_depth: int, timeout_rate: float) -> GovernorSnapshot:
        self._queue_depth_samples.append(float(max(0, int(queue_depth))))
        self._timeout_rate_samples.append(max(0.0, min(1.0, float(timeout_rate))))

        violations: list[str] = []
        e2e_p95 = _percentile95(self._e2e_samples_ms)
        preproc_p95 = _percentile95(self._preproc_samples_ms)
        queue_p95 = _percentile95(self._queue_depth_samples)
        timeout_p95 = _percentile95(self._timeout_rate_samples)

        if e2e_p95 > float(self._config.slo_e2e_p95_ms):
            violations.append("e2e_p95")
            self._metric_call("inc_slo_violation", "e2e_p95")
        if preproc_p95 > float(self._config.slo_preproc_p95_ms):
            violations.append("preproc_p95")
            self._metric_call("inc_slo_violation", "preproc_p95")
        if queue_p95 > float(self._config.slo_queue_depth_threshold):
            violations.append("queue_depth")
            self._metric_call("inc_slo_violation", "queue_depth")
        if timeout_p95 > float(self._config.slo_timeout_rate_threshold):
            violations.append("timeout_rate")
            self._metric_call("inc_slo_violation", "timeout_rate")

        if violations:
            self._recover_ticks = 0
            if self._mode != "THROTTLED":
                self._mode = "THROTTLED"
                self._metric_call("inc_throttle_enter")
                self._set_mode_gauge(self._mode)
            self._reason = f"slo_pressure:{violations[0]}"
            return self.snapshot()

        if self._mode == "THROTTLED":
            self._recover_ticks += 1
            if self._recover_ticks >= max(1, int(self._config.slo_recover_ticks)):
                self._mode = "NORMAL"
                self._reason = "slo_recovered"
                self._set_mode_gauge(self._mode)
                return self.snapshot()
            self._reason = "slo_recovering"
            return self.snapshot()

        self._reason = "normal"
        return self.snapshot()

    def _set_mode_gauge(self, state: str) -> None:
        self._metric_call("set_throttle_state", "NORMAL", 1 if state == "NORMAL" else 0)
        self._metric_call("set_throttle_state", "THROTTLED", 1 if state == "THROTTLED" else 0)

    def _metric_call(self, method: str, *args: object) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)


def _percentile95(values: deque[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = int(math.ceil(0.95 * len(sorted_values))) - 1
    idx = min(max(idx, 0), len(sorted_values) - 1)
    return float(sorted_values[idx])
