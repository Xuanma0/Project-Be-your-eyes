from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_seg_metrics_bbox_iou_min(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_seg_gt_min"

    output_md = tmp_path / "report_seg_gt_min.md"
    output_json = tmp_path / "report_seg_gt_min.json"

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
    seg = quality.get("seg", {})
    latency = seg.get("latencyMs", {})

    assert isinstance(seg, dict)
    assert bool(seg.get("present")) is True
    assert int(seg.get("framesTotal", 0)) == 2
    assert int(seg.get("framesWithGt", 0)) == 2
    assert int(seg.get("framesWithPred", 0)) == 2

    coverage = float(seg.get("coverage", -1.0))
    precision = float(seg.get("precision", -1.0))
    recall = float(seg.get("recall", -1.0))
    f1 = float(seg.get("f1At50", -1.0))
    mean_iou = float(seg.get("meanIoU", -1.0))

    assert 0.0 <= coverage <= 1.0
    assert coverage == 1.0
    assert 0.0 <= precision <= 1.0
    assert 0.0 <= recall <= 1.0
    assert 0.0 <= f1 <= 1.0
    assert 0.0 <= mean_iou <= 1.0
    assert abs(f1 - 0.5) < 1e-6

    assert int(latency.get("count", 0)) == 2
    assert 30 <= int(latency.get("p50", 0)) <= 50
    assert 30 <= int(latency.get("p90", 0)) <= 50
    assert int(latency.get("max", 0)) == 50

    assert isinstance(seg.get("topMisses", []), list)
    assert isinstance(seg.get("topFP", []), list)
    assert seg.get("maskF1_50") is None
    assert seg.get("maskCoverage") is None
    assert seg.get("maskMeanIoU") is None
