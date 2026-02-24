from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_plan_context_alignment_metrics_basic(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_plan_context_alignment_min"
    run_pkg = tmp_path / "plan_context_alignment_run_pkg"
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
    plan_context = report.get("planContext", {})
    assert isinstance(plan_context, dict)
    assert bool(plan_context.get("present")) is True
    seg = plan_context.get("seg", {})
    seg = seg if isinstance(seg, dict) else {}
    assert float(seg.get("hitRate", 0.0) or 0.0) == 1.0
    assert float(seg.get("coverageMean", 0.0) or 0.0) >= 1.0
