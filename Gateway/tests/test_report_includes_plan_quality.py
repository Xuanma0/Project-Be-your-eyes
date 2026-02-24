from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_report_includes_plan_quality(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_risk_gt_and_pov_min"
    out_md = tmp_path / "report_plan_quality.md"
    out_json = tmp_path / "report_plan_quality.json"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_package_dir),
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
    plan_quality = payload.get("planQuality", {})
    assert isinstance(plan_quality, dict)
    consistency = plan_quality.get("consistency", {})
    assert isinstance(consistency, dict)
    assert bool(consistency.get("critical_requires_stop")) is True
    assert "score" in plan_quality
