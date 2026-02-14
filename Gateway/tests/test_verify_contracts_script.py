from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_verify_contracts_check_lock() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "Gateway" / "scripts" / "verify_contracts.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check-lock"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    message = "\n".join([result.stdout, result.stderr]).strip()
    assert result.returncode == 0, message
    assert "[check-lock] ok" in result.stdout
