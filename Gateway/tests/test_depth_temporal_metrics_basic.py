from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_depth_temporal_metrics_basic(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_depth_temporal_min"
    run_pkg = tmp_path / "run_pkg_depth_temporal"
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

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))
    quality = payload.get("quality", {})
    quality = quality if isinstance(quality, dict) else {}
    depth_temporal = quality.get("depthTemporal", {})
    depth_temporal = depth_temporal if isinstance(depth_temporal, dict) else {}
    assert bool(depth_temporal.get("present")) is True

    jitter = depth_temporal.get("jitterAbs", {})
    jitter = jitter if isinstance(jitter, dict) else {}
    flicker = depth_temporal.get("flickerRateNear", {})
    flicker = flicker if isinstance(flicker, dict) else {}
    drift = depth_temporal.get("scaleDriftProxy", {})
    drift = drift if isinstance(drift, dict) else {}

    assert float(jitter.get("p90", 0.0) or 0.0) > 0.30
    assert float(flicker.get("mean", 0.0) or 0.0) > 0.20
    assert float(drift.get("p90", 0.0) or 0.0) > 0.30
    assert int(depth_temporal.get("refViewStrategyDiversityCount", 0) or 0) >= 2
