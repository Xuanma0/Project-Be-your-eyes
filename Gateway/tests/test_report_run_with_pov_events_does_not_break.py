from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_run_with_pov_events_does_not_break(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "pov_ir_v1_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    ingest_script = gateway_dir / "scripts" / "ingest_pov_ir.py"
    report_script = gateway_dir / "scripts" / "report_run.py"
    pov_ir_path = run_pkg / "pov" / "pov_ir_v1.json"
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"

    ingest_result = subprocess.run(
        [
            sys.executable,
            str(ingest_script),
            "--run-package",
            str(run_pkg),
            "--pov-ir",
            str(pov_ir_path),
            "--strict",
            "1",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ingest_result.returncode == 0, f"stdout={ingest_result.stdout}\nstderr={ingest_result.stderr}"

    report_result = subprocess.run(
        [
            sys.executable,
            str(report_script),
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
    assert report_result.returncode == 0, f"stdout={report_result.stdout}\nstderr={report_result.stderr}"

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))
    quality = payload.get("quality", {})
    assert isinstance(quality, dict)
    assert bool(quality.get("hasGroundTruth", False)) is False
    event_schema = quality.get("eventSchema", {})
    assert isinstance(event_schema, dict)
    assert event_schema.get("source") == "eventsV1Jsonl"
