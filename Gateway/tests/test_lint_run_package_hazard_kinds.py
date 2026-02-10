from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_lint_unknown_hazard_kind_warn_and_strict_fail(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "lint_run_package.py"
    source = tests_dir / "fixtures" / "run_package_with_gt_min"
    run_dir = tmp_path / "run_unknown_hazard"
    shutil.copytree(source, run_dir)

    risk_path = run_dir / "ground_truth" / "depth_risk.jsonl"
    rows = [
        {"frameSeq": 1, "hazards": [{"hazardKind": "glass_wall", "severity": "warning"}]},
        {"frameSeq": 2, "hazards": []},
    ]
    risk_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n", encoding="utf-8")

    non_strict = subprocess.run(
        [sys.executable, str(script), "--run-package", str(run_dir)],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert non_strict.returncode == 0, non_strict.stdout + "\n" + non_strict.stderr
    assert "hazardUnknownKinds:" in non_strict.stdout

    strict = subprocess.run(
        [sys.executable, str(script), "--run-package", str(run_dir), "--strict"],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode != 0
    assert "unknown hazard kinds" in strict.stdout.lower()
