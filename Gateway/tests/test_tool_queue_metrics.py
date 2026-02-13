from __future__ import annotations

import io
import json
import re
import time

from fastapi.testclient import TestClient

from main import app

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


def test_tool_queue_exec_metrics_histogram_count_grows() -> None:
    with TestClient(app) as client:
        client.post("/api/dev/reset")
        client.post("/api/fault/clear")

        before = _parse_metrics(client.get("/metrics").text)
        for _ in range(20):
            files = {"image": ("frame.jpg", io.BytesIO(b"img"), "image/jpeg")}
            meta = json.dumps({"ttlMs": 5000, "preserveOld": True})
            response = client.post("/api/frame", files=files, data={"meta": meta})
            assert response.status_code == 200

        after = _wait_completed(client, before, expected_delta=20)
        queue_count_delta = _metric_total(after, "byes_tool_queue_ms_count") - _metric_total(
            before, "byes_tool_queue_ms_count"
        )
        exec_count_delta = _metric_total(after, "byes_tool_exec_ms_count") - _metric_total(
            before, "byes_tool_exec_ms_count"
        )
        assert queue_count_delta > 0
        assert exec_count_delta > 0
