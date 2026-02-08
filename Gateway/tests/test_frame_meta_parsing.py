from __future__ import annotations

import io
import json
import re

from fastapi.testclient import TestClient

from main import app

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([^\s]+)")
_LABEL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
SeriesKey = tuple[str, tuple[tuple[str, str], ...]]


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


def test_frame_upload_legacy_bytes_ok_and_meta_missing_counted() -> None:
    with TestClient(app) as client:
        client.post("/api/dev/reset")
        before = parse_metrics(client.get("/metrics").text)
        response = client.post(
            "/api/frame",
            content=b"jpeg-bytes",
            headers={"Content-Type": "image/jpeg"},
        )
        assert response.status_code == 200
        after = parse_metrics(client.get("/metrics").text)
        missing_delta = metric_total(after, "byes_frame_meta_missing_total") - metric_total(
            before, "byes_frame_meta_missing_total"
        )
        assert int(round(missing_delta)) == 1


def test_frame_upload_multipart_meta_ok_and_meta_present_counted() -> None:
    with TestClient(app) as client:
        client.post("/api/dev/reset")
        before = parse_metrics(client.get("/metrics").text)
        meta_obj = {
            "frameMeta": {
                "frameSeq": 7,
                "deviceTsMs": 1234567890,
                "coordFrame": "World",
                "intrinsics": {
                    "fx": 560.0,
                    "fy": 560.0,
                    "cx": 320.0,
                    "cy": 180.0,
                    "width": 640,
                    "height": 360,
                },
                "pose": {
                    "position": {"x": 0.0, "y": 1.2, "z": 0.0},
                    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                },
            },
        }
        response = client.post(
            "/api/frame",
            files={"image": ("frame.jpg", io.BytesIO(b"abc"), "image/jpeg")},
            data={"meta": json.dumps(meta_obj, ensure_ascii=False)},
        )
        assert response.status_code == 200
        after = parse_metrics(client.get("/metrics").text)
        present_delta = metric_total(after, "byes_frame_meta_present_total") - metric_total(
            before, "byes_frame_meta_present_total"
        )
        assert int(round(present_delta)) == 1


def test_frame_upload_meta_bad_json_no_500_and_parse_error_counted() -> None:
    with TestClient(app) as client:
        client.post("/api/dev/reset")
        before = parse_metrics(client.get("/metrics").text)
        response = client.post(
            "/api/frame",
            files={"image": ("frame.jpg", io.BytesIO(b"abc"), "image/jpeg")},
            data={"meta": "{bad-json"},
        )
        assert response.status_code == 200
        after = parse_metrics(client.get("/metrics").text)
        parse_error_delta = metric_total(after, "byes_frame_meta_parse_error_total") - metric_total(
            before, "byes_frame_meta_parse_error_total"
        )
        assert int(round(parse_error_delta)) == 1
