from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_dataset_benchmark_matrix_smoke(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "run_dataset_benchmark.py"

    src_pkg = tests_dir / "fixtures" / "run_package_with_risk_gt_min"
    root = tmp_path / "root"
    pkg = root / "pkg_a"
    shutil.copytree(src_pkg, pkg)

    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "name": "baseline_reference",
                        "services": {"seg": "reference", "depth": "reference", "ocr": "reference"},
                        "env": {"BYES_ENABLE_SEG": "1", "BYES_ENABLE_DEPTH": "1", "BYES_ENABLE_OCR": "1"},
                    },
                    {
                        "name": "sam3_fixture",
                        "services": {"seg": "sam3", "depth": "reference", "ocr": "reference"},
                        "env": {"BYES_ENABLE_SEG": "1", "BYES_SAM3_MODE": "fixture"},
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

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
            "--matrix",
            "1",
            "--profiles",
            str(profiles_path),
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

    assert (out_dir / "baseline_reference" / "latest.json").exists()
    assert (out_dir / "sam3_fixture" / "latest.json").exists()
    summary_json = out_dir / "summary.json"
    assert summary_json.exists()
    summary = json.loads(summary_json.read_text(encoding="utf-8-sig"))
    profiles = summary.get("profiles")
    assert isinstance(profiles, list)
    names = {str(item.get("name")) for item in profiles if isinstance(item, dict)}
    assert {"baseline_reference", "sam3_fixture"}.issubset(names)

    latest_csv = out_dir / "latest.csv"
    assert latest_csv.exists()
    header = latest_csv.read_text(encoding="utf-8-sig").splitlines()[0]
    assert "profile" in header
    assert "services" in header
