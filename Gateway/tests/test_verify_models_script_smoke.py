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
