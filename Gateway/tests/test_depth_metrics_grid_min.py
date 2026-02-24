from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_depth_metrics_grid_min(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_depth_gt_min"

    output_md = tmp_path / "report_depth_gt_min.md"
    output_json = tmp_path / "report_depth_gt_min.json"

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
    depth = quality.get("depth", {})
    latency = depth.get("latencyMs", {})

    assert isinstance(depth, dict)
    assert bool(depth.get("present")) is True
    assert int(depth.get("framesTotal", 0)) == 2
    assert int(depth.get("framesWithGt", 0)) == 2
    assert int(depth.get("framesWithPred", 0)) == 2
    assert float(depth.get("coverage", -1.0)) == 1.0

    abs_rel = float(depth.get("absRel", -1.0))
    rmse = float(depth.get("rmse", -1.0))
    delta1 = float(depth.get("delta1", -1.0))
    assert 0.0 <= abs_rel < 1.0
    assert rmse >= 0.0
    assert 0.0 <= delta1 <= 1.0

    assert int(latency.get("count", 0)) == 2
    assert int(latency.get("p50", 0)) >= 35
    assert int(latency.get("p90", 0)) >= 55
    assert int(latency.get("max", 0)) == 55

    top_bad = depth.get("topBadCells", [])
    assert isinstance(top_bad, list)

