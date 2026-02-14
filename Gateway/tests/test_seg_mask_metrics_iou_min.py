from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_seg_mask_metrics_iou_min(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_seg_mask_gt_min"

    output_md = tmp_path / "report_seg_mask_gt_min.md"
    output_json = tmp_path / "report_seg_mask_gt_min.json"

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
    seg = payload.get("quality", {}).get("seg", {})

    assert bool(seg.get("present")) is True
    assert int(seg.get("framesTotal", 0)) == 2
    assert int(seg.get("framesWithGt", 0)) == 2
    assert int(seg.get("framesWithPred", 0)) == 2

    # bbox metrics remain available
    assert 0.0 <= float(seg.get("f1At50", -1.0)) <= 1.0
    assert 0.0 <= float(seg.get("meanIoU", -1.0)) <= 1.0

    # mask metrics are added and bounded
    mask_f1 = seg.get("maskF1_50")
    mask_cov = seg.get("maskCoverage")
    mask_iou = seg.get("maskMeanIoU")
    assert mask_f1 is not None
    assert mask_cov is not None
    assert mask_iou is not None
    assert 0.0 <= float(mask_f1) <= 1.0
    assert 0.0 <= float(mask_cov) <= 1.0
    assert 0.0 <= float(mask_iou) <= 1.0

    assert int(seg.get("maskFramesWithGt", 0)) == 2
    assert int(seg.get("maskFramesWithPred", 0)) == 2
    assert isinstance(seg.get("maskTopMisses", []), list)
    assert isinstance(seg.get("maskTopFP", []), list)
