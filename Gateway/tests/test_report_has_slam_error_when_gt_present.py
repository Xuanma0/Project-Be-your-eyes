from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_has_slam_error_when_gt_present(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_slam_gt_tum_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    report_script = gateway_dir / "scripts" / "report_run.py"
    out_md = tmp_path / "report.md"
    out_json = tmp_path / "report.json"
    result = subprocess.run(
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
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))
    slam_error = payload.get("quality", {}).get("slamError", {})
    assert isinstance(slam_error, dict)
    assert bool(slam_error.get("present")) is True
    assert slam_error.get("ate_rmse_m") is not None
    assert slam_error.get("rpe_trans_rmse_m") is not None
    coverage = slam_error.get("coverage", {})
    assert isinstance(coverage, dict)
    assert int(coverage.get("pairsMatched", 0) or 0) >= 1

