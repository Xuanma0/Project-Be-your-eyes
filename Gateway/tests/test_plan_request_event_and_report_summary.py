from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_plan_request_event_and_report_summary(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_plan_request_min"
    run_pkg = tmp_path / "plan_request_run_pkg"
    shutil.copytree(fixture_src, run_pkg)

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
    summary = report.get("planRequest", {})
    assert isinstance(summary, dict)
    assert bool(summary.get("present")) is True
    assert int(summary.get("events", 0) or 0) >= 1
    assert "segCharsP90" in summary
    assert "povCharsP90" in summary
    assert "segTruncSegmentsDroppedTotal" in summary
