from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_includes_slam_alignment_fields(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_pyslam_tum_relative_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    ingest_script = gateway_dir / "scripts" / "ingest_pyslam_tum.py"
    report_script = gateway_dir / "scripts" / "report_run.py"
    tum_path = run_pkg / "pyslam" / "online.txt"
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"

    ingest_result = subprocess.run(
        [
            sys.executable,
            str(ingest_script),
            "--run-package",
            str(run_pkg),
            "--tum",
            str(tum_path),
            "--align-mode",
            "auto",
            "--tum-time-base",
            "auto",
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
    slam = payload.get("quality", {}).get("slam", {})
    assert isinstance(slam, dict)
    alignment = slam.get("alignment", {})
    assert isinstance(alignment, dict)
    assert bool(alignment.get("present")) is True
    residual = alignment.get("residualMs", {})
    assert isinstance(residual, dict)
    assert residual.get("p90") is not None
