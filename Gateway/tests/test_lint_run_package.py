from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_lint_run_package_smoke() -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "lint_run_package.py"
    run_package = tests_dir / "fixtures" / "run_package_with_safety_events_min"

    result = subprocess.run(
        [sys.executable, str(script), "--run-package", str(run_package)],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "normalizedEvents:" in result.stdout
    assert "droppedEvents:" in result.stdout
    assert "framesDeclared:" in result.stdout
    assert "framesActual:" in result.stdout
