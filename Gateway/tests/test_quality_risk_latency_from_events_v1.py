from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_report_includes_risk_latency_and_timings_from_events_v1(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"

    run_package_dir = tmp_path / "run_package_risk_latency_min"
    events_dir = run_package_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "scenarioTag": "risk_latency_min",
        "startMs": 1707000000000,
        "endMs": 1707000000500,
        "wsJsonl": "ws_events.jsonl",
        "eventsV1Jsonl": "events/events_v1.jsonl",
        "metricsBefore": "metrics_before.txt",
        "metricsAfter": "metrics_after.txt",
        "frameCountSent": 2,
        "eventCountAccepted": 2,
        "errors": [],
    }
    (run_package_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_package_dir / "ws_events.jsonl").write_text("", encoding="utf-8")
    (run_package_dir / "metrics_before.txt").write_text("byes_frame_received_total 1\n", encoding="utf-8")
    (run_package_dir / "metrics_after.txt").write_text("byes_frame_received_total 2\n", encoding="utf-8")

    events = [
        {
            "schemaVersion": "byes.event.v1",
            "category": "tool",
            "name": "risk.hazards",
            "phase": "result",
            "status": "ok",
            "frameSeq": 1,
            "latencyMs": 100,
            "payload": {
                "backend": "http",
                "model": "risk-v1",
                "endpoint": "http://127.0.0.1:19120/risk",
                "debug": {
                    "timings": {
                        "decodeMs": 10,
                        "depthMs": 200,
                        "featureMs": 30,
                        "ruleMs": 5,
                        "totalMs": 245,
                    }
                },
            },
        },
        {
            "schemaVersion": "byes.event.v1",
            "category": "tool",
            "name": "risk.hazards",
            "phase": "result",
            "status": "ok",
            "frameSeq": 2,
            "latencyMs": 300,
            "payload": {
                "backend": "http",
                "model": "risk-v1",
                "endpoint": "http://127.0.0.1:19120/risk",
                "debug": {"timings": {"depthMs": 260, "totalMs": 320}},
            },
        },
    ]
    events_path = events_dir / "events_v1.jsonl"
    events_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n", encoding="utf-8")

    output_md = tmp_path / "report.md"
    output_json = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_package_dir),
            "--output",
            str(output_md),
            "--output-json",
            str(output_json),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    payload = json.loads(output_json.read_text(encoding="utf-8-sig"))
    quality = payload.get("quality", {})
    risk_latency = quality.get("riskLatencyMs", {})
    risk_timings = quality.get("riskTimingsMs", {})
    depth_timing = risk_timings.get("depthMs", {})

    assert risk_latency.get("count") == 2
    assert risk_latency.get("p90") == 300
    assert risk_latency.get("max") == 300
    assert depth_timing.get("count") == 2
    assert depth_timing.get("p90") == 260
    assert depth_timing.get("max") == 260
    assert risk_timings.get("decodeMs", {}).get("count") == 1
