from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_has_costmap_and_context(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_costmap_min"
    run_pkg = tmp_path / "costmap_run_pkg"
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
    costmap = quality.get("costmap", {})
    costmap = costmap if isinstance(costmap, dict) else {}
    assert bool(costmap.get("present")) is True
    assert float(costmap.get("coverage", 0.0) or 0.0) >= 1.0
    latency = costmap.get("latencyMs", {})
    latency = latency if isinstance(latency, dict) else {}
    assert int(latency.get("p90", 0) or 0) > 0

    ctx = report.get("costmapContext", {})
    ctx = ctx if isinstance(ctx, dict) else {}
    assert bool(ctx.get("present")) is True
    out = ctx.get("out", {})
    out = out if isinstance(out, dict) else {}
    assert int(out.get("charsTotalP90", 0) or 0) > 0
    trunc = ctx.get("truncation", {})
    trunc = trunc if isinstance(trunc, dict) else {}
    assert "truncationRate" in trunc
