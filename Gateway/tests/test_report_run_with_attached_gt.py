from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _gateway_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _attach_script() -> Path:
    return _gateway_dir() / "scripts" / "attach_ground_truth.py"


def _report_script() -> Path:
    return _gateway_dir() / "scripts" / "report_run.py"


def test_report_run_with_attached_gt(tmp_path: Path) -> None:
    fixtures = Path(__file__).resolve().parent / "fixtures"
    src_pkg = fixtures / "run_package_without_gt_min"
    run_pkg = tmp_path / "run_package_without_gt_min"
    shutil.copytree(src_pkg, run_pkg)

    ocr_gt = fixtures / "ground_truth_samples" / "ocr_ok.jsonl"
    risk_gt = fixtures / "ground_truth_samples" / "risk_ok.jsonl"

    attach = subprocess.run(
        [
            sys.executable,
            str(_attach_script()),
            "--run-package",
            str(run_pkg),
            "--ocr",
            str(ocr_gt),
            "--risk",
            str(risk_gt),
        ],
        cwd=_gateway_dir(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert attach.returncode == 0, f"stdout={attach.stdout}\nstderr={attach.stderr}"

    out_md = tmp_path / "report_with_attached_gt.md"
    out_json = tmp_path / "report_with_attached_gt.json"
    report = subprocess.run(
        [
            sys.executable,
            str(_report_script()),
            "--run-package",
            str(run_pkg),
            "--output",
            str(out_md),
            "--output-json",
            str(out_json),
        ],
        cwd=_gateway_dir(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert report.returncode == 0, f"stdout={report.stdout}\nstderr={report.stderr}"

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))
    quality = payload.get("quality")
    assert isinstance(quality, dict)
    assert quality.get("hasGroundTruth") is True

    ocr = quality.get("ocr")
    assert isinstance(ocr, dict)
    assert "intentCoverage" in ocr
    assert "gtHitRate" in ocr
    assert "falsePositiveRate" in ocr
    assert "topMismatches" in ocr

    depth = quality.get("depthRisk")
    assert isinstance(depth, dict)
    assert "detectionDelayFrames" in depth
    assert "topMisses" in depth

    breakdown = quality.get("qualityScoreBreakdown")
    assert isinstance(breakdown, list)
