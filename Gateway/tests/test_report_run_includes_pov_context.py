from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_report_run_includes_pov_context(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "pov_ir_v1_min"
    out_md = tmp_path / "report_pov_context.md"
    out_json = tmp_path / "report_pov_context.json"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_package_dir),
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
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))
    pov_context = payload.get("povContext", {})
    assert isinstance(pov_context, dict)
    out_stats = pov_context.get("out", {})
    assert int(out_stats.get("tokenApprox", 0) or 0) >= 1
    assert int(out_stats.get("decisions", 0) or 0) >= 1
