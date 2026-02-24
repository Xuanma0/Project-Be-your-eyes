from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import main as gateway_main
from main import app


def _make_run_package(root: Path) -> Path:
    run_pkg = root / "runpkg"
    (run_pkg / "events").mkdir(parents=True, exist_ok=True)
    manifest = {
        "runId": "confirm-run",
        "eventsV1Jsonl": "events/events_v1.jsonl",
    }
    (run_pkg / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return run_pkg


def test_confirm_response_latency(monkeypatch, tmp_path: Path) -> None:
    run_pkg = _make_run_package(tmp_path)
    events_path = run_pkg / "events" / "events_v1.jsonl"
    request_row = {
        "schemaVersion": "byes.event.v1",
        "tsMs": 1000,
        "runId": "confirm-run",
        "frameSeq": 1,
        "component": "gateway",
        "category": "ui",
        "name": "ui.confirm_request",
        "phase": "result",
        "status": "ok",
        "latencyMs": None,
        "payload": {"confirmId": "x", "text": "Confirm?", "timeoutMs": 3000},
    }
    events_path.write_text(json.dumps(request_row, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(gateway_main, "_now_ms", lambda: 1500)

    with TestClient(app) as client:
        resp = client.post(
            "/api/confirm/response",
            json={
                "runId": "confirm-run",
                "frameSeq": 1,
                "confirmId": "x",
                "accepted": True,
                "runPackage": str(run_pkg),
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert int(body.get("latencyMs", -1)) == 500

    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    response_rows = [row for row in rows if str(row.get("name", "")) == "ui.confirm_response"]
    assert response_rows
    response_row = response_rows[-1]
    assert int(response_row.get("latencyMs", -1)) == 500
    payload = response_row.get("payload", {})
    assert int(payload.get("latencyMs", -1)) == 500
