from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_verify_models_script_smoke() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "Gateway" / "scripts" / "verify_models.py"

    result = subprocess.run(
        [sys.executable, str(script), "--quiet"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "models enabled=" in result.stdout

    env = os.environ.copy()
    env["BYES_ENABLE_SEG"] = "1"
    env["BYES_SEG_BACKEND"] = "http"
    env["BYES_SEG_HTTP_URL"] = ""
    result_missing = subprocess.run(
        [sys.executable, str(script), "--check", "--quiet"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_missing.returncode != 0
    assert "missingRequired=" in result_missing.stdout

    env_ocr = os.environ.copy()
    env_ocr["BYES_ENABLE_OCR"] = "1"
    env_ocr["BYES_SERVICE_OCR_PROVIDER"] = "http"
    env_ocr["BYES_SERVICE_OCR_ENDPOINT"] = ""
    env_ocr["BYES_OCR_HTTP_URL"] = ""
    result_ocr_missing = subprocess.run(
        [sys.executable, str(script), "--check", "--quiet"],
        cwd=repo_root,
        env=env_ocr,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_ocr_missing.returncode != 0
    assert "missingRequired=" in result_ocr_missing.stdout

    env_slam = os.environ.copy()
    env_slam["BYES_ENABLE_SLAM"] = "1"
    env_slam["BYES_SLAM_BACKEND"] = "http"
    env_slam["BYES_SLAM_HTTP_URL"] = ""
    env_slam["BYES_SERVICE_SLAM_ENDPOINT"] = ""
    result_slam_missing = subprocess.run(
        [sys.executable, str(script), "--check", "--quiet"],
        cwd=repo_root,
        env=env_slam,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_slam_missing.returncode != 0
    assert "missingRequired=" in result_slam_missing.stdout

    env_sam3 = os.environ.copy()
    env_sam3["BYES_ENABLE_SEG"] = "1"
    env_sam3["BYES_SEG_BACKEND"] = "http"
    env_sam3["BYES_SEG_HTTP_URL"] = "http://127.0.0.1:19271/seg"
    env_sam3["BYES_SERVICE_SEG_HTTP_DOWNSTREAM"] = "sam3"
    env_sam3["BYES_SAM3_CKPT_PATH"] = ""
    result_sam3_missing = subprocess.run(
        [sys.executable, str(script), "--check", "--quiet"],
        cwd=repo_root,
        env=env_sam3,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_sam3_missing.returncode != 0
    assert "missingRequired=" in result_sam3_missing.stdout

    env_da3 = os.environ.copy()
    env_da3["BYES_ENABLE_DEPTH"] = "1"
    env_da3["BYES_DEPTH_BACKEND"] = "http"
    env_da3["BYES_DEPTH_HTTP_URL"] = "http://127.0.0.1:19281/depth"
    env_da3["BYES_SERVICE_DEPTH_HTTP_DOWNSTREAM"] = "da3"
    env_da3["BYES_DA3_MODEL_PATH"] = ""
    result_da3_missing = subprocess.run(
        [sys.executable, str(script), "--check", "--quiet"],
        cwd=repo_root,
        env=env_da3,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_da3_missing.returncode != 0
    assert "missingRequired=" in result_da3_missing.stdout
