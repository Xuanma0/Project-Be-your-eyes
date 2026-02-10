from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from byes.inference.backends.http import HttpRiskBackend
from byes.quality_metrics import extract_inference_summary_from_ws_events


def test_http_risk_model_passthrough_and_report_summary(monkeypatch, tmp_path: Path) -> None:
    expected_model = "heuristic-risk-v2+depth=synth"

    async def _fake_post(self, url: str, json: dict | None = None, **kwargs):  # noqa: ANN001
        del self, url, json, kwargs

        class _Response:
            status_code = 200

            @staticmethod
            def json() -> dict[str, object]:
                return {
                    "hazards": [{"hazardKind": "dropoff", "severity": "critical"}],
                    "model": expected_model,
                }

        return _Response()

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    backend = HttpRiskBackend(url="http://127.0.0.1:9002/risk", timeout_ms=800, model_id="mock-risk")
    result = asyncio.run(backend.infer(b"frame", frame_seq=1, ts_ms=1700000000000))

    assert backend.model_id == expected_model
    assert result.payload.get("model") == expected_model
    assert result.status == "ok"

    ws_events_path = tmp_path / "ws_events.jsonl"
    event = {
        "schemaVersion": "byes.event.v1",
        "tsMs": 1700000000050,
        "frameSeq": 1,
        "component": "gateway",
        "category": "tool",
        "name": "risk.hazards",
        "phase": "result",
        "status": "ok",
        "latencyMs": 50,
        "payload": {
            "hazards": [{"hazardKind": "dropoff", "severity": "critical"}],
            "backend": "http",
            "model": backend.model_id,
            "endpoint": backend.endpoint,
        },
    }
    ws_events_path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    inference = extract_inference_summary_from_ws_events(ws_events_path)
    risk = inference.get("risk", {})
    assert risk.get("backend") == "http"
    assert risk.get("model") == expected_model
    assert risk.get("endpoint") == "http://127.0.0.1:9002/risk"
