from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_report_for_fixture(tmp_path: Path, fixture_name: str) -> dict:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / fixture_name
    out_json = tmp_path / f"{fixture_name}.json"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_package_dir),
            "--output",
            str(tmp_path / f"{fixture_name}.md"),
            "--output-json",
            str(out_json),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(out_json.read_text(encoding="utf-8-sig"))


def test_quality_metrics_equivalence_old_vs_schema_v1(tmp_path: Path) -> None:
    old_payload = _run_report_for_fixture(tmp_path, "run_package_with_safety_events_min")
    new_payload = _run_report_for_fixture(tmp_path, "run_package_with_schema_v1_events_min")

    old_quality = old_payload["quality"]
    new_quality = new_payload["quality"]

    old_ocr = old_quality["ocr"]
    new_ocr = new_quality["ocr"]
    assert old_ocr["intentCoverage"] == new_ocr["intentCoverage"]
    assert old_ocr["resultCoverage"] == new_ocr["resultCoverage"]

    old_f1 = old_quality["depthRisk"]["overall"]["f1"]
    new_f1 = new_quality["depthRisk"]["overall"]["f1"]
    assert old_f1 == new_f1

    old_safety = old_quality["safetyBehavior"]
    new_safety = new_quality["safetyBehavior"]
    assert old_safety["confirm"]["timeouts"] == new_safety["confirm"]["timeouts"]
    assert old_safety["latch"]["count"] == new_safety["latch"]["count"]
    assert old_safety["preempt"]["count"] == new_safety["preempt"]["count"]

    assert old_quality["qualityScore"] == new_quality["qualityScore"]

    old_reasons = {item.get("reason") for item in old_quality.get("qualityScoreBreakdown", [])}
    new_reasons = {item.get("reason") for item in new_quality.get("qualityScoreBreakdown", [])}
    assert old_reasons == new_reasons
