from __future__ import annotations

import io
import json
import re
import time

from fastapi.testclient import TestClient

from main import app, gateway

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


def _speedup_mock_tools() -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = 0
    ocr = gateway.registry.get("mock_ocr")
    if ocr is not None and hasattr(ocr, "_delay_ms"):
        ocr._delay_ms = 0


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


def _metric_total(samples: dict[SeriesKey, float], metric_name: str) -> float:
    return sum(value for (name, _labels), value in samples.items() if name == metric_name)


def _metric_with_labels(samples: dict[SeriesKey, float], metric_name: str, labels: dict[str, str]) -> float:
    labels_key = tuple(sorted(labels.items(), key=lambda item: item[0]))
    return samples.get((metric_name, labels_key), 0.0)


def _send_frames(client: TestClient, count: int, preserve_old: bool = True) -> None:
    meta_payload: dict[str, object] = {"ttlMs": 5000}
    if preserve_old:
        meta_payload["preserveOld"] = True
    meta = json.dumps(meta_payload)
    for _ in range(count):
        files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
        resp = client.post("/api/frame", files=files, data={"meta": meta})
        assert resp.status_code == 200


def _wait_completed(client: TestClient, before: dict[SeriesKey, float], expected_delta: int) -> dict[SeriesKey, float]:
    deadline = time.time() + 25.0
    while time.time() < deadline:
        current = _parse_metrics(client.get("/metrics").text)
        completed = _metric_total(current, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        if completed >= expected_delta:
            return current
        time.sleep(0.1)
    return _parse_metrics(client.get("/metrics").text)


def _wait_metric_delta_positive(
    client: TestClient,
    before: dict[SeriesKey, float],
    metric_name: str,
    labels: dict[str, str],
    timeout_sec: float = 8.0,
) -> dict[SeriesKey, float]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        current = _parse_metrics(client.get("/metrics").text)
        delta = _metric_with_labels(current, metric_name, labels) - _metric_with_labels(before, metric_name, labels)
        if delta > 0:
            return current
        time.sleep(0.1)
    return _parse_metrics(client.get("/metrics").text)


def test_preempt_skips_slow_lane_on_critical_risk() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")

        before = _parse_metrics(client.get("/metrics").text)
        fault_resp = client.post(
            "/api/fault/set",
            json={"tool": "mock_risk", "mode": "critical", "value": True},
        )
        assert fault_resp.status_code == 200

        try:
            _send_frames(client, 50, preserve_old=True)
            after = _wait_completed(client, before, 50)
        finally:
            client.post("/api/fault/clear")

        frame_received_delta = _metric_total(after, "byes_frame_received_total") - _metric_total(
            before, "byes_frame_received_total"
        )
        frame_completed_delta = _metric_total(after, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        e2e_count_delta = _metric_total(after, "byes_e2e_latency_ms_count") - _metric_total(
            before, "byes_e2e_latency_ms_count"
        )
        safemode_enter_delta = _metric_total(after, "byes_safemode_enter_total") - _metric_total(
            before, "byes_safemode_enter_total"
        )
        preempt_enter_delta = _metric_with_labels(
            after,
            "byes_preempt_enter_total",
            {"reason": "critical_risk"},
        ) - _metric_with_labels(
            before,
            "byes_preempt_enter_total",
            {"reason": "critical_risk"},
        )
        ocr_invoked_delta = _metric_with_labels(
            after,
            "byes_tool_invoked_total",
            {"tool": "mock_ocr"},
        ) - _metric_with_labels(
            before,
            "byes_tool_invoked_total",
            {"tool": "mock_ocr"},
        )
        ocr_skipped_preempt_delta = _metric_with_labels(
            after,
            "byes_tool_skipped_total",
            {"tool": "mock_ocr", "reason": "preempted_by_critical_risk"},
        ) - _metric_with_labels(
            before,
            "byes_tool_skipped_total",
            {"tool": "mock_ocr", "reason": "preempted_by_critical_risk"},
        )

        assert int(round(frame_received_delta)) == 50
        assert int(round(frame_completed_delta)) == 50
        assert int(round(e2e_count_delta)) == 50
        assert int(round(safemode_enter_delta)) == 0
        assert preempt_enter_delta > 0
        assert int(round(ocr_invoked_delta)) == 0
        assert ocr_skipped_preempt_delta > 0


def test_baseline_not_preempted() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")

        before = _parse_metrics(client.get("/metrics").text)
        _send_frames(client, 30, preserve_old=True)
        _ = _wait_completed(client, before, 30)
        after = _wait_metric_delta_positive(
            client,
            before,
            "byes_tool_invoked_total",
            {"tool": "mock_ocr"},
        )

        preempt_enter_delta = _metric_with_labels(
            after,
            "byes_preempt_enter_total",
            {"reason": "critical_risk"},
        ) - _metric_with_labels(
            before,
            "byes_preempt_enter_total",
            {"reason": "critical_risk"},
        )
        ocr_invoked_delta = _metric_with_labels(
            after,
            "byes_tool_invoked_total",
            {"tool": "mock_ocr"},
        ) - _metric_with_labels(
            before,
            "byes_tool_invoked_total",
            {"tool": "mock_ocr"},
        )

        assert preempt_enter_delta == 0
        assert ocr_invoked_delta > 0


def test_preempt_window_skips_slow_for_grace_period() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")

        before = _parse_metrics(client.get("/metrics").text)
        fault_resp = client.post(
            "/api/fault/set",
            json={"tool": "mock_risk", "mode": "critical", "value": True, "durationMs": 300},
        )
        assert fault_resp.status_code == 200
        try:
            _send_frames(client, 6, preserve_old=True)
            time.sleep(0.4)
            _send_frames(client, 24, preserve_old=True)
            _ = _wait_completed(client, before, 30)
            after = _wait_metric_delta_positive(
                client,
                before,
                "byes_tool_skipped_total",
                {"tool": "mock_ocr", "reason": "preempt_window_active"},
            )
        finally:
            client.post("/api/fault/clear")

        preempt_window_skip_delta = _metric_with_labels(
            after,
            "byes_tool_skipped_total",
            {"tool": "mock_ocr", "reason": "preempt_window_active"},
        ) - _metric_with_labels(
            before,
            "byes_tool_skipped_total",
            {"tool": "mock_ocr", "reason": "preempt_window_active"},
        )
        safemode_enter_delta = _metric_total(after, "byes_safemode_enter_total") - _metric_total(
            before, "byes_safemode_enter_total"
        )
        assert preempt_window_skip_delta > 0
        assert int(round(safemode_enter_delta)) == 0


def test_preempt_window_cancels_inflight_slow() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")

        # Build slow-lane backlog first.
        slow_fault_resp = client.post(
            "/api/fault/set",
            json={"tool": "mock_ocr", "mode": "slow", "value": 1200, "durationMs": 4000},
        )
        assert slow_fault_resp.status_code == 200

        before = _parse_metrics(client.get("/metrics").text)
        _send_frames(client, 8, preserve_old=True)
        time.sleep(0.4)

        critical_resp = client.post(
            "/api/fault/set",
            json={"tool": "mock_risk", "mode": "critical", "value": True, "durationMs": 300},
        )
        assert critical_resp.status_code == 200
        try:
            _send_frames(client, 42, preserve_old=True)
            _ = _wait_completed(client, before, 50)
            after = _parse_metrics(client.get("/metrics").text)
        finally:
            client.post("/api/fault/clear")

        canceled_delta = _metric_with_labels(
            after,
            "byes_preempt_cancel_inflight_total",
            {"lane": "slow"},
        ) - _metric_with_labels(
            before,
            "byes_preempt_cancel_inflight_total",
            {"lane": "slow"},
        )
        dropped_delta = _metric_with_labels(
            after,
            "byes_preempt_drop_queued_total",
            {"lane": "slow"},
        ) - _metric_with_labels(
            before,
            "byes_preempt_drop_queued_total",
            {"lane": "slow"},
        )
        frame_received_delta = _metric_total(after, "byes_frame_received_total") - _metric_total(
            before, "byes_frame_received_total"
        )
        frame_completed_delta = _metric_total(after, "byes_frame_completed_total") - _metric_total(
            before, "byes_frame_completed_total"
        )
        e2e_count_delta = _metric_total(after, "byes_e2e_latency_ms_count") - _metric_total(
            before, "byes_e2e_latency_ms_count"
        )

        assert canceled_delta > 0 or dropped_delta > 0
        assert int(round(frame_received_delta)) == 50
        assert int(round(frame_completed_delta)) == 50
        assert int(round(e2e_count_delta)) == 50
