from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_confirm_response_metrics(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_confirm_response_min"
    run_pkg = tmp_path / "confirm_response_metrics_pkg"
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
    plan_ack = report.get("planAck", {})
    assert isinstance(plan_ack, dict)
    assert int(plan_ack.get("confirmResponsesFromUnity", 0) or 0) == 1
    latency = plan_ack.get("confirmResponseLatencyMs", {})
    assert isinstance(latency, dict)
    assert int(latency.get("p90", 0) or 0) == 300

    confirm_summary = report.get("confirm", {})
    assert isinstance(confirm_summary, dict)
    assert int(confirm_summary.get("responses", 0) or 0) == 1
