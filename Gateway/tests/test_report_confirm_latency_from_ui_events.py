from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _make_run_package(root: Path) -> Path:
    run_pkg = root / "runpkg"
    (run_pkg / "events").mkdir(parents=True, exist_ok=True)
    manifest = {
        "runId": "confirm-report-run",
        "eventsV1Jsonl": "events/events_v1.jsonl",
        "metricsBefore": "metrics_before.txt",
        "metricsAfter": "metrics_after.txt",
    }
    (run_pkg / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_pkg / "metrics_before.txt").write_text("", encoding="utf-8")
    (run_pkg / "metrics_after.txt").write_text("", encoding="utf-8")

    rows = [
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": 1000,
            "runId": "confirm-report-run",
            "frameSeq": 1,
            "component": "gateway",
            "category": "ui",
            "name": "ui.confirm_request",
            "phase": "start",
            "status": "ok",
            "latencyMs": None,
            "payload": {"confirmId": "c-lat", "text": "Proceed?", "timeoutMs": 3000},
        },
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": 1500,
            "runId": "confirm-report-run",
            "frameSeq": 1,
            "component": "gateway",
            "category": "ui",
            "name": "ui.confirm_response",
            "phase": "result",
            "status": "ok",
            "latencyMs": 500,
            "payload": {"confirmId": "c-lat", "accepted": True, "latencyMs": 500},
        },
    ]
    (run_pkg / "events" / "events_v1.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return run_pkg


def test_report_confirm_latency_from_ui_events(tmp_path: Path) -> None:
    run_pkg = _make_run_package(tmp_path)
    gateway_dir = Path(__file__).resolve().parent.parent
    script = gateway_dir / "scripts" / "report_run.py"
    out_md = tmp_path / "report.md"
    out_json = tmp_path / "report.json"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_pkg),
            "--output",
            str(out_md),
            "--output-json",
            str(out_json),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))
    confirm_latency = payload.get("quality", {}).get("safetyBehavior", {}).get("confirm", {}).get("latencyMs", {})
    assert isinstance(confirm_latency, dict)
    assert int(confirm_latency.get("count", 0) or 0) == 1
    assert int(confirm_latency.get("p50", -1) or -1) == 500
