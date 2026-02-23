from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_has_costmap_fused_metrics(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_costmap_fused_min"
    run_pkg = tmp_path / "costmap_fused_run_pkg"
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
    quality = report.get("quality", {})
    quality = quality if isinstance(quality, dict) else {}
    fused = quality.get("costmapFused", {})
    fused = fused if isinstance(fused, dict) else {}
    assert bool(fused.get("present")) is True
    assert float(fused.get("coverage", 0.0) or 0.0) >= 1.0

    stability = fused.get("stability", {})
    stability = stability if isinstance(stability, dict) else {}
    assert isinstance(stability.get("iouPrevP90"), (int, float))
    assert isinstance(stability.get("flickerRatePrevMean"), (int, float))
