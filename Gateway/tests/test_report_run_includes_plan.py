from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_report_run_includes_plan(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_risk_gt_and_pov_min"
    out_md = tmp_path / "report_plan.md"
    out_json = tmp_path / "report_plan.json"

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
    plan = payload.get("plan", {})
    assert isinstance(plan, dict)
    assert bool(plan.get("present")) is True
    assert str(plan.get("riskLevel", "")).strip()
    actions = plan.get("actions", {})
    assert isinstance(actions, dict)
    assert "count" in actions
    assert "guardrailsApplied" in plan
