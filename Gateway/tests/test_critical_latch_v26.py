from __future__ import annotations

import io
import json
import re
import time

from fastapi.testclient import TestClient

from byes.config import load_config
from byes.fusion import FusionEngine
from byes.metrics import GatewayMetrics
from byes.schema import CoordFrame, ToolResult, ToolStatus
from byes.tools.base import FrameInput, ToolLane
from byes.world_state import WorldState
from main import app, gateway

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="([^"]*)"')
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
        labels_raw = match.group(2)
        value_raw = match.group(3)
        try:
            value = float(value_raw)
        except ValueError:
            continue
        labels: tuple[tuple[str, str], ...] = tuple()
        if labels_raw:
            labels = tuple(sorted(_LABEL_RE.findall(labels_raw), key=lambda item: item[0]))
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
    timeout_sec: float = 12.0,
) -> dict[SeriesKey, float]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        current = _parse_metrics(client.get("/metrics").text)
        delta = _metric_with_labels(current, metric_name, labels) - _metric_with_labels(before, metric_name, labels)
        if delta > 0:
            return current
        time.sleep(0.1)
    return _parse_metrics(client.get("/metrics").text)


def _speedup_mock_risk() -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = 0


def test_critical_latch_upgrades_fast_risk_level() -> None:
    config = load_config()
    metrics = GatewayMetrics()
    world_state = WorldState(config, metrics=metrics)
    fusion = FusionEngine(config, metrics=metrics, world_state=world_state)

    ts_ms = int(time.time() * 1000)
    world_state.set_critical(ts_ms, 1500, "crosscheck", session_id="s1")
    frame = FrameInput(
        seq=1,
        ts_capture_ms=ts_ms,
        ttl_ms=3000,
        frame_bytes=b"frame",
        meta={"sessionId": "s1"},
    )
    risk_result = ToolResult(
        toolName="mock_risk",
        toolVersion="1.0",
        seq=1,
        tsCaptureMs=ts_ms,
        latencyMs=5,
        confidence=0.9,
        coordFrame=CoordFrame.WORLD,
        status=ToolStatus.OK,
        payload={
            "riskText": "Obstacle ahead",
            "summary": "Obstacle ahead",
            "riskLevel": "warn",
        },
    )
    fused = fusion.fuse_lane(
        frame=frame,
        lane=ToolLane.FAST,
        results=[risk_result],
        trace_id="1" * 32,
        span_id="2" * 16,
        health_status="NORMAL",
    )
    assert fused.stage1_events
    risk = fused.stage1_events[0]
    assert str(risk.riskLevel.value) == "critical"
    assert str(risk.payload.get("riskLevel")) == "critical"
    assert str(risk.payload.get("criticalReason")) == "crosscheck"

    samples = _parse_metrics(metrics.render().content.decode("utf-8", errors="ignore"))
    assert _metric_with_labels(
        samples,
        "byes_risklevel_upgrade_total",
        {"from_level": "warn", "to_level": "critical", "reason": "crosscheck"},
    ) > 0


def test_evidence_triggers_preempt_window_without_fault_critical() -> None:
    with TestClient(app) as client:
        _speedup_mock_risk()
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")

        slow_fault_resp = client.post(
            "/api/fault/set",
            json={"tool": "mock_ocr", "mode": "slow", "value": 700, "durationMs": 6000},
        )
        assert slow_fault_resp.status_code == 200

        before = _parse_metrics(client.get("/metrics").text)
        _send_frames(client, 1, preserve_old=True)
        crosscheck_resp = client.post(
            "/api/dev/crosscheck",
            json={"kind": "vision_without_depth", "durationMs": 2500},
        )
        assert crosscheck_resp.status_code == 200
        _send_frames(client, 20, preserve_old=True)
        _ = _wait_metric_delta_positive(
            client,
            before,
            "byes_critical_latch_enter_total",
            {"reason": "crosscheck"},
        )
        _send_frames(client, 29, preserve_old=True)
        after = _wait_completed(client, before, 50)
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
        latch_enter_delta = _metric_with_labels(
            after,
            "byes_critical_latch_enter_total",
            {"reason": "crosscheck"},
        ) - _metric_with_labels(
            before,
            "byes_critical_latch_enter_total",
            {"reason": "crosscheck"},
        )
        upgrade_delta = _metric_with_labels(
            after,
            "byes_risklevel_upgrade_total",
            {"from_level": "warn", "to_level": "critical", "reason": "crosscheck"},
        ) - _metric_with_labels(
            before,
            "byes_risklevel_upgrade_total",
            {"from_level": "warn", "to_level": "critical", "reason": "crosscheck"},
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
        cancel_delta = _metric_with_labels(
            after,
            "byes_preempt_cancel_inflight_total",
            {"lane": "slow"},
        ) - _metric_with_labels(
            before,
            "byes_preempt_cancel_inflight_total",
            {"lane": "slow"},
        )
        drop_delta = _metric_with_labels(
            after,
            "byes_preempt_drop_queued_total",
            {"lane": "slow"},
        ) - _metric_with_labels(
            before,
            "byes_preempt_drop_queued_total",
            {"lane": "slow"},
        )
        safemode_delta = _metric_total(after, "byes_safemode_enter_total") - _metric_total(
            before, "byes_safemode_enter_total"
        )

        assert int(round(frame_received_delta)) == 50
        assert int(round(frame_completed_delta)) == 50
        assert int(round(e2e_count_delta)) == 50
        assert latch_enter_delta > 0
        assert upgrade_delta > 0
        assert preempt_enter_delta > 0
        assert cancel_delta > 0 or drop_delta > 0
        assert int(round(safemode_delta)) == 0
