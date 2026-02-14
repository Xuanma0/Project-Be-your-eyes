from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_seg_prompt_contract_lock_contains_seg_request() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    lock_path = repo_root / "Gateway" / "contracts" / "contract.lock.json"
    payload = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    versions = payload.get("versions", {}) if isinstance(payload, dict) else {}
    assert isinstance(versions, dict)
    assert "byes.seg_request.v1" in versions


def test_seg_prompt_contract_lock_check_ok() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "Gateway" / "scripts" / "verify_contracts.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check-lock"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "[check-lock] ok" in result.stdout
