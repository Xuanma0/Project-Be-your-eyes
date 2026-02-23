from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_pyslam_run_fixture_writes_pyslam_dir(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_pyslam_run_fixture_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    script = gateway_dir / "scripts" / "run_pyslam_on_run_package.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_pkg),
            "--mode",
            "fixture",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    pyslam_dir = run_pkg / "pyslam"
    online = pyslam_dir / "byes_traj_online.txt"
    final = pyslam_dir / "byes_traj_final.txt"
    summary_path = pyslam_dir / "run_summary.json"

    assert online.exists() and online.is_file()
    assert final.exists() and final.is_file()
    assert len(online.read_text(encoding="utf-8-sig").strip()) > 0
    assert len(final.read_text(encoding="utf-8-sig").strip()) > 0
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    assert summary.get("mode") == "fixture"
    files_written = summary.get("filesWritten", [])
    assert isinstance(files_written, list)
    assert len(files_written) >= 2

