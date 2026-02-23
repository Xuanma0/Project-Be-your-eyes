from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_slam_eval_script_smoke(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "eval_slam_tum.py"
    fixture = tests_dir / "fixtures" / "run_package_with_slam_gt_tum_min"
    out_dir = tmp_path / "slam_eval_out"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(fixture),
            "--pred-glob",
            "events",
            "--align",
            "se3",
            "--delta-frames",
            "1",
            "--out",
            str(out_dir),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    payload = json.loads((out_dir / "latest.json").read_text(encoding="utf-8-sig"))
    ate = payload.get("ate_rmse_m")
    rpe = payload.get("rpe_trans_rmse_m")
    assert isinstance(ate, (int, float))
    assert isinstance(rpe, (int, float))
    assert 0.01 <= float(ate) <= 1.0
    assert 0.01 <= float(rpe) <= 1.0

