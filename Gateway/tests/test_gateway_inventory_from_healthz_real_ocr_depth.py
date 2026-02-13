from __future__ import annotations

import io
import json
import re
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


def _send_frames(client: TestClient, count: int) -> None:
    for _ in range(count):
        files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
        meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
        response = client.post("/api/frame", files=files, data={"meta": meta})
        assert response.status_code == 200


def _tool_names(client: TestClient) -> set[str]:
    response = client.get("/api/tools")
    assert response.status_code == 200
    payload = response.json()
    tools = payload.get("tools", [])
    out: set[str] = set()
    for item in tools:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                out.add(name)
    return out


def test_gateway_inventory_from_healthz_real_ocr_depth(monkeypatch) -> None:
    original_enable_real_ocr = gateway.config.enable_real_ocr
    original_enable_real_depth = gateway.config.enable_real_depth
    original_enabled_tools_csv = gateway.config.enabled_tools_csv
    original_enabled_tools = set(gateway._enabled_tools)  # noqa: SLF001

    object.__setattr__(gateway.config, "enable_real_ocr", True)
    object.__setattr__(gateway.config, "enable_real_depth", True)
    object.__setattr__(gateway.config, "enabled_tools_csv", "mock_risk,mock_ocr,real_ocr,real_depth")
    gateway._enabled_tools = gateway._parse_csv_tools(gateway.config.enabled_tools_csv)  # noqa: SLF001
    gateway.registry._tools.pop("real_ocr", None)  # noqa: SLF001
    gateway.registry._tools.pop("real_depth", None)  # noqa: SLF001

    async def _probe_not_ready(tool_name: str, endpoint: str) -> dict[str, Any]:
        if tool_name in {"real_ocr", "real_depth"}:
            return {
                "tool": tool_name,
                "endpoint": endpoint,
                "healthz": f"http://127.0.0.1/{tool_name}/healthz",
                "ready": False,
                "reason": "weights_missing",
                "backend": "onnxruntime",
                "model_id": f"{tool_name}-onnx",
                "version": "0.3.0",
                "warmed_up": False,
            }
        return {"tool": tool_name, "endpoint": endpoint, "ready": True, "reason": "ok"}

    monkeypatch.setattr(gateway, "_probe_external_service", _probe_not_ready)

    try:
        with TestClient(app) as client:
            client.post("/api/dev/reset")
            client.post("/api/fault/clear")
            client.post("/api/dev/intent", json={"intent": "scan_text", "durationMs": 10000})
            tools = _tool_names(client)
            assert "real_ocr" not in tools
            assert "real_depth" not in tools

            before = _parse_metrics(client.get("/metrics").text)
            _send_frames(client, 10)
            after = _parse_metrics(client.get("/metrics").text)

            ocr_unavailable_delta = _metric_with_labels(
                after,
                "byes_tool_skipped_total",
                {"tool": "real_ocr", "reason": "unavailable"},
            ) - _metric_with_labels(
                before,
                "byes_tool_skipped_total",
                {"tool": "real_ocr", "reason": "unavailable"},
            )
            depth_unavailable_delta = _metric_with_labels(
                after,
                "byes_tool_skipped_total",
                {"tool": "real_depth", "reason": "unavailable"},
            ) - _metric_with_labels(
                before,
                "byes_tool_skipped_total",
                {"tool": "real_depth", "reason": "unavailable"},
            )
            assert ocr_unavailable_delta >= 0
            assert depth_unavailable_delta >= 0
            assert _metric_with_labels(after, "byes_tool_skipped_total", {"tool": "real_ocr", "reason": "unavailable"}) > 0
            assert _metric_with_labels(after, "byes_tool_skipped_total", {"tool": "real_depth", "reason": "unavailable"}) > 0
    finally:
        gateway.registry._tools.pop("real_ocr", None)  # noqa: SLF001
        gateway.registry._tools.pop("real_depth", None)  # noqa: SLF001
        object.__setattr__(gateway.config, "enable_real_ocr", original_enable_real_ocr)
        object.__setattr__(gateway.config, "enable_real_depth", original_enable_real_depth)
        object.__setattr__(gateway.config, "enabled_tools_csv", original_enabled_tools_csv)
        gateway._enabled_tools = original_enabled_tools  # noqa: SLF001
