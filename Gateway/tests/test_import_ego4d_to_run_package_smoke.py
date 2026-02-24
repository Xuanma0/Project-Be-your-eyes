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


def _write_test_video(path: Path, *, width: int = 96, height: int = 64, frames: int = 10, fps: int = 10) -> None:
    cv2 = __import__("cv2")
    np = __import__("numpy")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, float(fps), (width, height))
    assert writer.isOpened(), "cv2 VideoWriter failed to open (mp4v)"
    for idx in range(frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :, 0] = (idx * 12) % 255
        frame[:, :, 1] = (idx * 19) % 255
        frame[:, :, 2] = (idx * 27) % 255
        writer.write(frame)
    writer.release()


def test_import_ego4d_to_run_package_smoke(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "import_ego4d_to_run_package.py"

    video_path = tmp_path / "tiny.mp4"
    _write_test_video(video_path, frames=10, fps=10)

    out_dir = tmp_path / "out_run_package"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--video-path",
            str(video_path),
            "--out",
            str(out_dir),
            "--fps",
            "5",
            "--max-frames",
            "5",
            "--overwrite",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    assert int(manifest.get("framesCount", 0)) == 5
    assert int(manifest.get("frameCountSent", 0)) == 5
    assert manifest.get("datasetTag") == "ego4d"

    lines = [line for line in (out_dir / "frames_meta.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assert len(lines) == 5

    errors = _lint_strict_errors(gateway_dir, out_dir)
    assert errors == 0
