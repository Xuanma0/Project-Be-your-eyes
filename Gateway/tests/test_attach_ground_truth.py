from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def _script_path() -> Path:
    return Path(__file__).resolve().parent.parent / "scripts" / "attach_ground_truth.py"


def _fixture_without_gt() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "run_package_without_gt_min"


def _fixture_gt_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "ground_truth_samples"


def test_attach_ground_truth_dir(tmp_path: Path) -> None:
    src = _fixture_without_gt()
    run_dir = tmp_path / "run_pkg"
    shutil.copytree(src, run_dir)

    cmd = [
        sys.executable,
        str(_script_path()),
        "--run-package",
        str(run_dir),
        "--ocr",
        str(_fixture_gt_dir() / "ocr_ok.jsonl"),
        "--risk",
        str(_fixture_gt_dir() / "risk_ok.jsonl"),
        "--match-window-frames",
        "3",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert (run_dir / "ground_truth" / "ocr.jsonl").exists()
    assert (run_dir / "ground_truth" / "depth_risk.jsonl").exists()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    gt = manifest.get("groundTruth", {})
    assert gt.get("version") == 1
    assert gt.get("ocrJsonl") == "ground_truth/ocr.jsonl"
    assert gt.get("riskJsonl") == "ground_truth/depth_risk.jsonl"
    assert gt.get("matchWindowFrames") == 3
    assert "sha256 manifest updates: not found (skipped)" in result.stdout


def test_attach_ground_truth_zip(tmp_path: Path) -> None:
    src = _fixture_without_gt()
    src_zip = tmp_path / "run_pkg.zip"
    with zipfile.ZipFile(src_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in src.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(src))

    cmd = [
        sys.executable,
        str(_script_path()),
        "--run-package",
        str(src_zip),
        "--ocr",
        str(_fixture_gt_dir() / "ocr_ok.jsonl"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    out_zip = tmp_path / "run_pkg_gt.zip"
    assert out_zip.exists()

    extract_dir = Path(tempfile.mkdtemp(prefix="attach_gt_zip_test_"))
    try:
        with zipfile.ZipFile(out_zip, "r") as zf:
            zf.extractall(extract_dir)
        assert (extract_dir / "ground_truth" / "ocr.jsonl").exists()
        manifest = json.loads((extract_dir / "manifest.json").read_text(encoding="utf-8-sig"))
        gt = manifest.get("groundTruth", {})
        assert gt.get("ocrJsonl") == "ground_truth/ocr.jsonl"
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
