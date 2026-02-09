from __future__ import annotations

from pathlib import Path

import httpx
import json

from scripts.replay_run_package import replay_run_package


def test_replay_run_package_http_calls(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "run_package_with_frames_min"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path in {
            "/api/dev/reset",
            "/api/dev/intent",
            "/api/dev/crosscheck",
            "/api/frame",
        }:
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/metrics":
            body = (
                "# HELP byes_frame_received_total test\n"
                "# TYPE byes_frame_received_total counter\n"
                "byes_frame_received_total 2\n"
                "byes_frame_completed_total{outcome=\"ok\"} 2\n"
                "byes_e2e_latency_ms_count 2\n"
                "byes_e2e_latency_ms_sum 20\n"
                "byes_ttfa_ms_count 2\n"
                "byes_ttfa_ms_sum 8\n"
            )
            return httpx.Response(200, text=body)
        if request.url.path == "/api/external_readiness":
            return httpx.Response(200, json={"tools": {}})
        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        result = replay_run_package(
            run_package=fixture_dir,
            base_url="http://127.0.0.1:8000",
            ws_url="ws://127.0.0.1:8000/ws/events",
            out_dir=tmp_path,
            interval_ms=0,
            apply_scenario_calls=True,
            do_reset=True,
            record_ws=False,
            auto_upload=False,
            client=client,
        )

    replay_dir = Path(result["replayDir"])
    assert replay_dir.exists()
    assert Path(result["reportMdPath"]).exists()
    assert Path(result["reportJsonPath"]).exists()
    assert result["sentFrames"] == 2
    events_v1 = replay_dir / "events" / "events_v1.jsonl"
    assert events_v1.exists()
    manifest = json.loads((replay_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest.get("eventsV1Jsonl") == "events/events_v1.jsonl"

    sequence = [path for path in calls if path in {"/api/dev/reset", "/api/dev/intent", "/api/dev/crosscheck", "/metrics", "/api/frame"}]
    assert sequence[:7] == [
        "/api/dev/reset",
        "/api/dev/intent",
        "/api/dev/crosscheck",
        "/metrics",
        "/api/frame",
        "/api/frame",
        "/metrics",
    ]
