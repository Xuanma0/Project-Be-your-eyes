from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _append_plan_generate_events(events_path: Path) -> None:
    rows = [
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": 1713003000100,
            "runId": "fixture-frame-user-e2e-kinds-min",
            "frameSeq": 1,
            "component": "gateway",
            "category": "plan",
            "name": "plan.generate",
            "phase": "result",
            "status": "ok",
            "latencyMs": 8,
            "payload": {"runId": "fixture-frame-user-e2e-kinds-min", "frameSeq": 1, "riskLevel": "warning"},
        },
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": 1713003001200,
            "runId": "fixture-frame-user-e2e-kinds-min",
            "frameSeq": 2,
            "component": "gateway",
            "category": "plan",
            "name": "plan.generate",
            "phase": "result",
            "status": "ok",
            "latencyMs": 9,
            "payload": {"runId": "fixture-frame-user-e2e-kinds-min", "frameSeq": 2, "riskLevel": "warning"},
        },
    ]
    with events_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_report_has_plan_ack_rates(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_frame_user_e2e_kinds_min"
    run_pkg = tmp_path / "plan_ack_run_pkg"
    shutil.copytree(fixture_src, run_pkg)
    _append_plan_generate_events(run_pkg / "events" / "events_v1.jsonl")

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

    report = json.loads(out_json.read_text(encoding="utf-8-sig"))
    plan_ack = report.get("planAck", {})
    assert isinstance(plan_ack, dict)
    assert bool(plan_ack.get("present")) is True
    assert int(plan_ack.get("framesWithPlan", 0) or 0) == 2
    assert int(plan_ack.get("framesWithAck", 0) or 0) == 2
    assert float(plan_ack.get("ttsAckRate", 0.0) or 0.0) == 0.5
    assert float(plan_ack.get("arAckRate", 0.0) or 0.0) == 0.5
    assert int(plan_ack.get("ackKindDiversity", 0) or 0) == 2
