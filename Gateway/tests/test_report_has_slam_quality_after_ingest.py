from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_has_slam_quality_after_ingest(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_pyslam_tum_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    ingest_script = gateway_dir / "scripts" / "ingest_pyslam_tum.py"
    report_script = gateway_dir / "scripts" / "report_run.py"
    tum_path = run_pkg / "pyslam" / "byes_traj.tum"
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
    slam = quality.get("slam", {})
    inference = payload.get("inference", {})
    slam_infer = inference.get("slam", {})

    assert isinstance(slam, dict)
    assert bool(slam.get("present")) is True
    assert int(slam.get("framesWithGt", 0)) == 2
    assert int(slam.get("framesWithPred", 0)) == 2
    assert float(slam.get("coverage", -1.0)) == 1.0

    assert slam_infer.get("backend") == "offline"
    assert str(slam_infer.get("model", "")).startswith("pyslam")
    assert slam_infer.get("endpoint") in {None, "", "None"}
