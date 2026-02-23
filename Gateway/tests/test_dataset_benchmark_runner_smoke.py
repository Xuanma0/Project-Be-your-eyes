from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_dataset_benchmark_runner_smoke(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "run_dataset_benchmark.py"

    src_pkg = tests_dir / "fixtures" / "run_package_with_risk_gt_min"
    root = tmp_path / "root"
    pkg = root / "pkg_a"
    shutil.copytree(src_pkg, pkg)

    out_dir = tmp_path / "bench_out"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(root),
            "--out",
            str(out_dir),
            "--replay",
            "0",
            "--max",
            "10",
            "--shuffle",
            "0",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    latest_json = out_dir / "latest.json"
    latest_csv = out_dir / "latest.csv"
    latest_md = out_dir / "latest.md"
    assert latest_json.exists()
    assert latest_csv.exists()
    assert latest_md.exists()

    payload = json.loads(latest_json.read_text(encoding="utf-8-sig"))
    rows = payload.get("rows", [])
    assert isinstance(rows, list)
    assert len(rows) >= 1


def test_dataset_benchmark_runner_max_limit(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "run_dataset_benchmark.py"

    src_pkg = tests_dir / "fixtures" / "run_package_with_risk_gt_min"
    root = tmp_path / "root"
    shutil.copytree(src_pkg, root / "pkg_a")
    shutil.copytree(src_pkg, root / "pkg_b")

    out_dir = tmp_path / "bench_out"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(root),
            "--out",
            str(out_dir),
            "--replay",
            "0",
            "--max",
            "1",
            "--shuffle",
            "0",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    payload = json.loads((out_dir / "latest.json").read_text(encoding="utf-8-sig"))
    assert int(payload.get("processed", -1)) == 1
    rows = payload.get("rows", [])
    assert isinstance(rows, list)
    assert len(rows) == 1
