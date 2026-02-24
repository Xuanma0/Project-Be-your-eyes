from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_lint_frame_ack_kind_counts_present() -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture = tests_dir / "fixtures" / "run_package_with_frame_user_e2e_kinds_min"
    script = gateway_dir / "scripts" / "lint_run_package.py"

    result = subprocess.run(
        [sys.executable, str(script), "--run-package", str(fixture)],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    summary: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        summary[key.strip()] = value.strip()
    assert int(summary.get("frameAckKindsPresent", "0") or 0) >= 2
    assert int(summary.get("frameAckTtsCount", "0") or 0) == 1
    assert int(summary.get("frameAckArCount", "0") or 0) == 1
