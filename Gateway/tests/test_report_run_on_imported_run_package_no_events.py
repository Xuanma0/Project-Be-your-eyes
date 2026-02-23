from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_report_run_on_imported_run_package_no_events(tmp_path: Path) -> None:
    cv2 = __import__("cv2")
    np = __import__("numpy")

    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    import_script = gateway_dir / "scripts" / "import_image_folder_to_run_package.py"
    report_script = gateway_dir / "scripts" / "report_run.py"

    image_dir = tmp_path / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(1, 3):
        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        frame[:, :, :] = idx * 60
        ok = cv2.imwrite(str(image_dir / f"img_{idx:02d}.jpg"), frame)
        assert ok

    run_pkg = tmp_path / "run_pkg"
    import_result = subprocess.run(
        [
            sys.executable,
            str(import_script),
            "--image-dir",
            str(image_dir),
            "--glob",
            "*.jpg",
            "--sample",
            "2",
            "--shuffle",
            "0",
            "--out",
            str(run_pkg),
            "--overwrite",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert import_result.returncode == 0, f"stdout={import_result.stdout}\nstderr={import_result.stderr}"

    out_md = tmp_path / "report.md"
    out_json = tmp_path / "report.json"
    report_result = subprocess.run(
        [
            sys.executable,
            str(report_script),
            "--run-package",
            str(run_pkg),
            "--output",
            str(out_md),
            "--output-json",
            str(out_json),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert report_result.returncode == 0, f"stdout={report_result.stdout}\nstderr={report_result.stderr}"
    assert out_json.exists()
    assert out_md.exists()
