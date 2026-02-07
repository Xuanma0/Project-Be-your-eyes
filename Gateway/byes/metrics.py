from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest


@dataclass
class MetricsResponse:
    content: bytes
    content_type: str


class GatewayMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or CollectorRegistry(auto_describe=True)
        self.byes_e2e_latency_ms = Histogram(
            "byes_e2e_latency_ms",
            "Gateway end-to-end latency in milliseconds",
            buckets=(20, 50, 100, 200, 350, 500, 800, 1200, 2000, 3000, 5000),
            registry=self._registry,
        )
        self.byes_tool_latency_ms = Histogram(
            "byes_tool_latency_ms",
            "Tool latency in milliseconds",
            labelnames=("tool",),
            buckets=(10, 20, 50, 100, 200, 350, 500, 800, 1200, 2000, 3000),
            registry=self._registry,
        )
        self.byes_deadline_miss_total = Counter(
            "byes_deadline_miss_total",
            "Number of missed deadlines/TTL drops",
            labelnames=("lane",),
            registry=self._registry,
        )
        self.byes_safemode_enter_total = Counter(
            "byes_safemode_enter_total",
            "Number of times gateway entered SAFE_MODE",
            registry=self._registry,
        )
        self.byes_queue_depth = Gauge(
            "byes_queue_depth",
            "Current queue depth by lane",
            labelnames=("lane",),
            registry=self._registry,
        )
        self.byes_backpressure_drop_total = Counter(
            "byes_backpressure_drop_total",
            "Dropped tasks caused by backpressure",
            labelnames=("lane",),
            registry=self._registry,
        )

    def observe_e2e_latency(self, latency_ms: int) -> None:
        self.byes_e2e_latency_ms.observe(max(0, latency_ms))

    def observe_tool_latency(self, tool: str, latency_ms: int) -> None:
        self.byes_tool_latency_ms.labels(tool=tool).observe(max(0, latency_ms))

    def inc_deadline_miss(self, lane: str) -> None:
        self.byes_deadline_miss_total.labels(lane=lane).inc()

    def inc_safemode_enter(self) -> None:
        self.byes_safemode_enter_total.inc()

    def set_queue_depth(self, lane: str, depth: int) -> None:
        self.byes_queue_depth.labels(lane=lane).set(max(0, depth))

    def inc_backpressure_drop(self, lane: str) -> None:
        self.byes_backpressure_drop_total.labels(lane=lane).inc()

    def render(self) -> MetricsResponse:
        return MetricsResponse(
            content=generate_latest(self._registry),
            content_type=CONTENT_TYPE_LATEST,
        )
