from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_ablation_pov_budget_script_smoke(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "run_ablation_pov_budget.py"
    run_package = tests_dir / "fixtures" / "run_package_with_risk_gt_and_pov_min"
    out_dir = tmp_path / "ablation_out"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_package),
            "--budgets",
            "128,256",
            "--mode",
            "decisions_plus_highlights",
            "--out",
            str(out_dir),
            "--use-http",
            "0",
            "--fail-on-critical-fn",
            "0",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    latest_json = out_dir / "latest.json"
    assert latest_json.exists()
    payload = json.loads(latest_json.read_text(encoding="utf-8-sig"))
    assert isinstance(payload, dict)

    rows = payload.get("rows", [])
    assert isinstance(rows, list)
    assert len(rows) == 2
    for row in rows:
        assert "context" in row and isinstance(row["context"], dict)
        assert "tokenApprox" in row["context"]
        assert "metrics" in row and isinstance(row["metrics"], dict)
        assert "qualityScore" in row["metrics"]

    recommendation = payload.get("recommendation", {})
    best = recommendation.get("bestMaxTokensApprox")
    assert best in [128, 256]
