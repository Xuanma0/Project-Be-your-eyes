from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_slam_metrics_tracking_rates_min(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_slam_pose_gt_min"

    output_md = tmp_path / "report_slam_gt_min.md"
    output_json = tmp_path / "report_slam_gt_min.json"

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
    slam = quality.get("slam", {})
    tracking = slam.get("tracking", {})
    latency = slam.get("latencyMs", {})

    assert isinstance(slam, dict)
    assert bool(slam.get("present")) is True
    assert int(slam.get("framesTotal", 0)) == 2
    assert int(slam.get("framesWithGt", 0)) == 2
    assert int(slam.get("framesWithPred", 0)) == 2
    assert float(slam.get("coverage", -1.0)) == 1.0

    assert 0.0 <= float(tracking.get("trackingRate", -1.0)) <= 1.0
    assert 0.0 <= float(tracking.get("lostRate", -1.0)) <= 1.0
    assert int(latency.get("count", 0)) == 2
    assert int(latency.get("p50", 0)) >= 30
    assert int(latency.get("p90", 0)) >= 50
    assert int(latency.get("max", 0)) == 50

