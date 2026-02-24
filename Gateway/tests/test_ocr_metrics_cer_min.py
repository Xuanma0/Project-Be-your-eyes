from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_ocr_metrics_cer_min(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_ocr_gt_min"

    output_md = tmp_path / "report_ocr_gt_min.md"
    output_json = tmp_path / "report_ocr_gt_min.json"

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
    ocr = quality.get("ocr", {})

    assert isinstance(ocr, dict)
    assert int(ocr.get("framesTotal", 0)) == 2
    assert int(ocr.get("framesWithGt", 0)) == 2
    assert int(ocr.get("framesWithPred", 0)) == 2
    assert float(ocr.get("coverage", -1.0)) == 1.0

    cer = float(ocr.get("cer", -1.0))
    exact = float(ocr.get("exactMatchRate", -1.0))
    assert 0.0 <= cer <= 1.0
    assert 0.0 <= exact <= 1.0
    assert cer > 0.0
    assert exact < 1.0

    latency = ocr.get("latencyMs", {})
    assert int(latency.get("count", 0)) == 2
    assert int(latency.get("p90", 0)) >= 55
