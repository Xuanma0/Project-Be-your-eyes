from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_report_run_includes_quality_when_ground_truth_exists(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_gt_min"

    output_md = tmp_path / "report_with_gt.md"
    output_json = tmp_path / "report_with_gt.json"

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
    assert output_md.exists()
    assert output_json.exists()

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    quality = payload.get("quality")
    assert isinstance(quality, dict)
    assert quality.get("hasGroundTruth") is True

    ocr = quality.get("ocr")
    assert isinstance(ocr, dict)
    assert ocr.get("framesWithGt") == 2
    assert "intentCoverage" in ocr
    assert "resultCoverage" in ocr
    assert "gtHitRate" in ocr
    assert "falsePositiveRate" in ocr
    assert isinstance(ocr.get("topMismatches"), list)

    depth_risk = quality.get("depthRisk")
    assert isinstance(depth_risk, dict)
    assert isinstance(depth_risk.get("overall"), dict)
    assert isinstance(depth_risk.get("detectionDelayFrames"), dict)
    assert isinstance(depth_risk.get("topMisses"), list)

    score = quality.get("qualityScore")
    assert isinstance(score, (int, float))
    assert isinstance(quality.get("qualityScoreBreakdown"), list)
