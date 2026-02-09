from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_report_run_includes_safety_behavior_and_findings(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_safety_events_min"

    output_md = tmp_path / "report_safety.md"
    output_json = tmp_path / "report_safety.json"

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

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    quality = payload.get("quality")
    assert isinstance(quality, dict)
    assert quality.get("hasGroundTruth") is True

    safety = quality.get("safetyBehavior")
    assert isinstance(safety, dict)
    confirm = safety.get("confirm", {})
    assert int(confirm.get("timeouts", 0)) >= 1
    assert int(confirm.get("missingResponseCount", 0)) >= 1

    findings = quality.get("topFindings", [])
    assert isinstance(findings, list)
    assert any(str(item.get("severity", "")).lower() == "critical" for item in findings)

    breakdown = quality.get("qualityScoreBreakdown", [])
    assert isinstance(breakdown, list)
    reasons = {str(item.get("reason", "")) for item in breakdown}
    assert "confirm_timeouts" in reasons or "confirm_missing_response" in reasons
