from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_pyslam_run_package_script_requires_root() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "Gateway" / "scripts" / "pyslam_run_package.py"
    run_package = repo_root / "Gateway" / "tests" / "fixtures" / "run_package_with_events_v1_min"

    env = os.environ.copy()
    env.pop("BYES_PYSLAM_REPO_PATH", None)

    result = subprocess.run(
        [sys.executable, str(script), "--run-package", str(run_package)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    combined = f"{result.stdout}\n{result.stderr}"
    assert "BYES_PYSLAM_REPO_PATH" in combined or "--pyslam-root" in combined
