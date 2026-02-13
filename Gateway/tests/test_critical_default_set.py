from __future__ import annotations

import io
import json
import re
import time

from fastapi.testclient import TestClient

from main import app, gateway

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
_REASON_TOKEN_RE = re.compile(
    r"^(critical_(timeout|error|unavailable|missing)|noncritical_(timeout|error|unavailable)|rate_limit|ws_disconnect|timeout_rate|tool_result)(:[a-z0-9_\\-]+)?$"
)
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


def _metric_total(samples: dict[SeriesKey, float], name: str) -> float:
    return sum(value for (metric_name, _labels), value in samples.items() if metric_name == name)


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


def _speedup_mock_tools() -> None:
    risk = gateway.registry.get("mock_risk")
    if risk is not None and hasattr(risk, "_delay_ms"):
        risk._delay_ms = 0
    ocr = gateway.registry.get("mock_ocr")
    if ocr is not None and hasattr(ocr, "_delay_ms"):
        ocr._delay_ms = 0


def test_critical_default_set_and_reason_tokens() -> None:
    with TestClient(app) as client:
        _speedup_mock_tools()
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")

        # Default config should not include not-yet-registered tools like risk_engine.
        configured_critical = {item.strip() for item in gateway.config.critical_tools_csv.split(",") if item.strip()}
        assert "mock_risk" in configured_critical
        assert "risk_engine" not in configured_critical

        before = _parse_metrics(client.get("/metrics").text)
        for _ in range(50):
            files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
            meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
            resp = client.post("/api/frame", files=files, data={"meta": meta})
            assert resp.status_code == 200
        after = _wait_completed(client, before, expected_delta=50)

        reasons: list[str] = []
        for (name, labels), value in after.items():
            if name != "byes_degradation_state_change_total" or value <= 0:
                continue
            reason = dict(labels).get("reason")
            if reason:
                reasons.append(reason)

        assert all("critical_recovered" not in reason for reason in reasons)
        assert all(_REASON_TOKEN_RE.match(reason) is not None for reason in reasons)
