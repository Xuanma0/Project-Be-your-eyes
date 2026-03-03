from __future__ import annotations

import io
import json
import re
import time
from typing import Any

from fastapi.testclient import TestClient

from main import app, gateway

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


class CaptureConnection:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def broadcast_json(self, obj: dict[str, Any]) -> None:
        self.messages.append(obj)


def parse_metrics(text: str) -> dict[SeriesKey, float]:
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
        value_raw = match.group(3)
        try:
            value = float(value_raw)
        except ValueError:
            continue
        labels: tuple[tuple[str, str], ...] = tuple()
        if raw_labels:
            labels = tuple(sorted(_LABEL_RE.findall(raw_labels), key=lambda item: item[0]))
        rows[(name, labels)] = value
    return rows


def metric_total(samples: dict[SeriesKey, float], name: str) -> float:
    return sum(value for (metric_name, _labels), value in samples.items() if metric_name == name)


def metric_with_labels(samples: dict[SeriesKey, float], name: str, labels: dict[str, str]) -> float:
    labels_key = tuple(sorted(labels.items(), key=lambda item: item[0]))
    return samples.get((name, labels_key), 0.0)


def metric_delta(before: dict[SeriesKey, float], after: dict[SeriesKey, float], name: str) -> float:
    return metric_total(after, name) - metric_total(before, name)


def wait_completed_delta(client: TestClient, before: dict[SeriesKey, float], expected: int, timeout_sec: float = 20.0) -> dict[SeriesKey, float]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        current = parse_metrics(client.get("/metrics").text)
        completed = metric_total(current, "byes_frame_completed_total") - metric_total(before, "byes_frame_completed_total")
        received = metric_total(current, "byes_frame_received_total") - metric_total(before, "byes_frame_received_total")
        if completed >= expected and received >= expected:
            return current
        time.sleep(0.1)
    return parse_metrics(client.get("/metrics").text)


def wait_metric_delta_positive(
    client: TestClient,
    before: dict[SeriesKey, float],
    metric_name: str,
    labels: dict[str, str],
    timeout_sec: float = 8.0,
) -> dict[SeriesKey, float]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        current = parse_metrics(client.get("/metrics").text)
        delta = metric_with_labels(current, metric_name, labels) - metric_with_labels(before, metric_name, labels)
        if delta > 0:
            return current
        time.sleep(0.1)
    return parse_metrics(client.get("/metrics").text)


def send_frames(client: TestClient, n: int) -> None:
    meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
    for _ in range(n):
        files = {"image": ("frame.jpg", io.BytesIO(b"123"), "image/jpeg")}
        response = client.post("/api/frame", files=files, data={"meta": meta})
        assert response.status_code == 200


def speedup_mock_tools() -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = 0
    ocr = gateway.registry.get("mock_ocr")
    if ocr is not None and hasattr(ocr, "_delay_ms"):
        ocr._delay_ms = 0


def test_v12_baseline_frame_e2e_accounting() -> None:
    with TestClient(app) as client:
        client.post("/api/dev/reset")
        speedup_mock_tools()
        client.post("/api/fault/clear")
        before = parse_metrics(client.get("/metrics").text)

        send_frames(client, 50)
        after = wait_completed_delta(client, before, expected=50)

        received_delta = metric_delta(before, after, "byes_frame_received_total")
        completed_delta = metric_delta(before, after, "byes_frame_completed_total")
        e2e_count_delta = metric_delta(before, after, "byes_e2e_latency_ms_count")

        ok_delta = metric_with_labels(after, "byes_frame_completed_total", {"outcome": "ok"}) - metric_with_labels(
            before,
            "byes_frame_completed_total",
            {"outcome": "ok"},
        )
        safemode_delta = metric_with_labels(
            after,
            "byes_frame_completed_total",
            {"outcome": "safemode_suppressed"},
        ) - metric_with_labels(
            before,
            "byes_frame_completed_total",
            {"outcome": "safemode_suppressed"},
        )

        assert int(round(received_delta)) == 50
        assert int(round(completed_delta)) == 50
        assert int(round(ok_delta + safemode_delta)) == 50
        assert int(round(e2e_count_delta)) == 50


def test_v12_timeout_fault_frame_completion_and_skips() -> None:
    with TestClient(app) as client:
        speedup_mock_tools()
        client.post("/api/dev/reset")
        stabilize_before = parse_metrics(client.get("/metrics").text)
        send_frames(client, 1)
        _ = wait_completed_delta(client, stabilize_before, expected=1)
        assert client.get("/api/health").json().get("state") == "NORMAL"
        before = parse_metrics(client.get("/metrics").text)
        original_connections = gateway.connections
        capture = CaptureConnection()
        gateway.connections = capture  # type: ignore[assignment]

        try:
            response = client.post(
                "/api/fault/set",
                json={"tool": "all", "mode": "timeout", "value": True},
            )
            assert response.status_code == 200
            capture.messages.clear()

            send_frames(client, 50)
            _ = wait_completed_delta(client, before, expected=50)
            after = wait_metric_delta_positive(
                client,
                before,
                "byes_tool_skipped_total",
                {"tool": "mock_ocr", "reason": "safe_mode"},
            )
        finally:
            client.post("/api/fault/clear")
            gateway.connections = original_connections  # type: ignore[assignment]

        received_delta = metric_delta(before, after, "byes_frame_received_total")
        completed_delta = metric_delta(before, after, "byes_frame_completed_total")
        safemode_enter_delta = metric_delta(before, after, "byes_safemode_enter_total")

        safemode_suppressed_delta = metric_with_labels(
            after,
            "byes_frame_completed_total",
            {"outcome": "safemode_suppressed"},
        ) - metric_with_labels(
            before,
            "byes_frame_completed_total",
            {"outcome": "safemode_suppressed"},
        )

        timeout_delta = metric_with_labels(after, "byes_tool_timeout_total", {"tool": "mock_risk"}) - metric_with_labels(
            before,
            "byes_tool_timeout_total",
            {"tool": "mock_risk"},
        )
        skipped_safe_mode_delta = metric_with_labels(
            after,
            "byes_tool_skipped_total",
            {"tool": "mock_ocr", "reason": "safe_mode"},
        ) - metric_with_labels(
            before,
            "byes_tool_skipped_total",
            {"tool": "mock_ocr", "reason": "safe_mode"},
        )
        emitted_types = {
            str(item.get("type"))
            for item in capture.messages
            if isinstance(item, dict) and item.get("type") is not None
        }

        assert int(round(received_delta)) == 50
        assert int(round(completed_delta)) == 50
        assert int(round(safemode_enter_delta)) == 1
        assert safemode_suppressed_delta > 0
        assert timeout_delta > 0
        assert skipped_safe_mode_delta > 0
        assert "perception" not in emitted_types
        assert emitted_types.issubset({"risk", "health"})
