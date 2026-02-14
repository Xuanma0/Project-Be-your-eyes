from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def test_plan_request_contract_visible_and_locked() -> None:
    gateway_root = Path(__file__).resolve().parents[1]
    script = gateway_root / "scripts" / "verify_contracts.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check-lock"],
        cwd=gateway_root.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    with TestClient(app) as client:
        response = client.get("/api/contracts")
        assert response.status_code == 200, response.text
        payload = response.json()

    versions = payload.get("versions", {})
    assert isinstance(versions, dict)
    row = versions.get("byes.plan_request.v1")
    assert isinstance(row, dict)
    sha = str(row.get("sha256", ""))
    assert len(sha) == 64
