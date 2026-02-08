from __future__ import annotations

import io
import json
import re
import time

from fastapi.testclient import TestClient

from byes.runtime_stats import RuntimeStats
from main import app, gateway

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


def _parse_metrics(text: str) -> dict[SeriesKey, float]:
    rows: dict[SeriesKey, float] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        raw_labels = match.group(2)
        try:
            value = float(match.group(3))
        except ValueError:
            continue
        labels: tuple[tuple[str, str], ...] = tuple()
        if raw_labels:
            labels = tuple(sorted(_LABEL_RE.findall(raw_labels), key=lambda item: item[0]))
        rows[(name, labels)] = value
    return rows


def _metric_value(samples: dict[SeriesKey, float], metric_name: str, labels: dict[str, str]) -> float:
    labels_key = tuple(sorted(labels.items(), key=lambda item: item[0]))
    return samples.get((metric_name, labels_key), 0.0)


def _metric_total(samples: dict[SeriesKey, float], metric_name: str) -> float:
    return sum(value for (name, _), value in samples.items() if name == metric_name)


def _wait_completed(client: TestClient, before: dict[SeriesKey, float], expected_delta: int) -> dict[SeriesKey, float]:
    deadline = time.time() + 20.0
    while time.time() < deadline:
        current = _parse_metrics(client.get("/metrics").text)
        completed = _metric_total(current, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        if completed >= expected_delta:
            return current
        time.sleep(0.1)
    return _parse_metrics(client.get("/metrics").text)


def test_planner_adaptive_budget_skip_keeps_risk_path_alive() -> None:
    original_runtime = gateway.runtime_stats
    planner_runtime = getattr(gateway.planner, "_runtime_stats", None)
    scheduler_runtime = getattr(gateway.scheduler, "_runtime_stats", None)
    with TestClient(app) as client:
        try:
            client.post("/api/dev/reset")
            client.post("/api/fault/clear")

            runtime = RuntimeStats(window_size=50, ema_alpha=0.2)
            for _ in range(20):
                runtime.observe("mock_ocr", "slow", queue_ms=700, exec_ms=900)
            gateway.runtime_stats = runtime
            if hasattr(gateway.planner, "_runtime_stats"):
                gateway.planner._runtime_stats = runtime  # noqa: SLF001
            if hasattr(gateway.scheduler, "_runtime_stats"):
                gateway.scheduler._runtime_stats = runtime  # noqa: SLF001

            before = _parse_metrics(client.get("/metrics").text)
            for _ in range(12):
                files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
                meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
                response = client.post("/api/frame", files=files, data={"meta": meta})
                assert response.status_code == 200

            after = _wait_completed(client, before, expected_delta=12)
            planner_skip_delta = _metric_value(
                after,
                "byes_planner_skip_total",
                {"tool": "mock_ocr", "reason": "latency_pred_exceeds_budget"},
            ) - _metric_value(
                before,
                "byes_planner_skip_total",
                {"tool": "mock_ocr", "reason": "latency_pred_exceeds_budget"},
            )
            tool_skip_delta = _metric_value(
                after,
                "byes_tool_skipped_total",
                {"tool": "mock_ocr", "reason": "latency_pred_exceeds_budget"},
            ) - _metric_value(
                before,
                "byes_tool_skipped_total",
                {"tool": "mock_ocr", "reason": "latency_pred_exceeds_budget"},
            )
            risk_invoked_delta = _metric_value(
                after,
                "byes_tool_invoked_total",
                {"tool": "mock_risk"},
            ) - _metric_value(
                before,
                "byes_tool_invoked_total",
                {"tool": "mock_risk"},
            )
            assert planner_skip_delta > 0
            assert tool_skip_delta > 0
            assert risk_invoked_delta > 0
        finally:
            gateway.runtime_stats = original_runtime
            if hasattr(gateway.planner, "_runtime_stats"):
                gateway.planner._runtime_stats = planner_runtime  # noqa: SLF001
            if hasattr(gateway.scheduler, "_runtime_stats"):
                gateway.scheduler._runtime_stats = scheduler_runtime  # noqa: SLF001
