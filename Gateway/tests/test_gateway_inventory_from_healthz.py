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


def _metric_with_labels(samples: dict[SeriesKey, float], name: str, labels: dict[str, str]) -> float:
    labels_key = tuple(sorted(labels.items(), key=lambda item: item[0]))
    return samples.get((name, labels_key), 0.0)


def _metric_total(samples: dict[SeriesKey, float], name: str) -> float:
    return sum(value for (metric_name, _labels), value in samples.items() if metric_name == name)


def _send_frames(client: TestClient, count: int) -> None:
    for _ in range(count):
        files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
        meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
        response = client.post("/api/frame", files=files, data={"meta": meta})
        assert response.status_code == 200


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


def test_gateway_inventory_from_healthz_not_ready_marks_unavailable_skip(monkeypatch) -> None:
    original_enable_real_depth = gateway.config.enable_real_depth
    original_enabled_tools_csv = gateway.config.enabled_tools_csv
    original_enabled_tools = set(gateway._enabled_tools)  # noqa: SLF001

    object.__setattr__(gateway.config, "enable_real_depth", True)
    object.__setattr__(gateway.config, "enabled_tools_csv", "mock_risk,mock_ocr,real_depth")
    gateway._enabled_tools = gateway._parse_csv_tools(gateway.config.enabled_tools_csv)  # noqa: SLF001
    gateway.registry._tools.pop("real_depth", None)  # noqa: SLF001

    async def _fake_probe(tool_name: str, endpoint: str) -> dict[str, Any]:
        if tool_name == "real_depth":
            return {
                "tool": tool_name,
                "endpoint": endpoint,
                "healthz": "http://127.0.0.1:8012/healthz",
                "ready": False,
                "reason": "not_ready",
                "backend": "mock",
                "model_id": "byes-real-depth-v1",
                "version": "0.2.1",
                "warmed_up": False,
            }
        return {
            "tool": tool_name,
            "endpoint": endpoint,
            "healthz": "",
            "ready": True,
            "reason": "ok",
        }

    monkeypatch.setattr(gateway, "_probe_external_service", _fake_probe)

    try:
        with TestClient(app) as client:
            client.post("/api/dev/reset")
            client.post("/api/fault/clear")
            before = _parse_metrics(client.get("/metrics").text)
            _send_frames(client, 12)
            after = _wait_completed(client, before, expected_delta=12)

            unavailable_skip_delta = _metric_with_labels(
                after,
                "byes_tool_skipped_total",
                {"tool": "real_depth", "reason": "unavailable"},
            ) - _metric_with_labels(
                before,
                "byes_tool_skipped_total",
                {"tool": "real_depth", "reason": "unavailable"},
            )
            assert unavailable_skip_delta > 0
    finally:
        gateway.registry._tools.pop("real_depth", None)  # noqa: SLF001
        object.__setattr__(gateway.config, "enable_real_depth", original_enable_real_depth)
        object.__setattr__(gateway.config, "enabled_tools_csv", original_enabled_tools_csv)
        gateway._enabled_tools = original_enabled_tools  # noqa: SLF001
