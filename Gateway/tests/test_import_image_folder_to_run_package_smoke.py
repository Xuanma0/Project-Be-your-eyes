from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _lint_strict_errors(gateway_dir: Path, run_package: Path) -> int:
    lint_script = gateway_dir / "scripts" / "lint_run_package.py"
    result = subprocess.run(
        [
            sys.executable,
            str(lint_script),
            "--run-package",
            str(run_package),
            "--strict",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    for line in result.stdout.splitlines():
        if line.strip().startswith("errors:"):
            return int(line.split(":", 1)[1].strip())
    raise AssertionError(f"errors line missing in lint output:\n{result.stdout}")


def test_import_image_folder_to_run_package_smoke(tmp_path: Path) -> None:
    cv2 = __import__("cv2")
    np = __import__("numpy")

    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "import_image_folder_to_run_package.py"

    image_dir = tmp_path / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(1, 4):
        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        frame[:, :, 0] = idx * 20
        frame[:, :, 1] = idx * 30
        frame[:, :, 2] = idx * 40
        ok = cv2.imwrite(str(image_dir / f"img_{idx:02d}.jpg"), frame)
        assert ok

    out_dir = tmp_path / "out_run_package"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--image-dir",
            str(image_dir),
            "--glob",
            "*.jpg",
            "--sample",
            "10",
            "--shuffle",
            "0",
            "--out",
            str(out_dir),
            "--overwrite",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    assert int(manifest.get("framesCount", 0)) == 3
    assert int(manifest.get("frameCountSent", 0)) == 3
    assert manifest.get("datasetTag") == "imagenet_det_test"

    lines = [line for line in (out_dir / "frames_meta.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assert len(lines) == 3

    errors = _lint_strict_errors(gateway_dir, out_dir)
    assert errors == 0
