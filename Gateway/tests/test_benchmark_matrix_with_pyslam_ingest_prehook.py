from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_benchmark_matrix_with_pyslam_ingest_prehook(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "run_dataset_benchmark.py"

    src_pkg = tests_dir / "fixtures" / "run_package_with_pyslam_dir_min"
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
                        "env": {},
                    },
                    {
                        "name": "slam_offline_pyslam",
                        "services": {"seg": "reference", "depth": "reference", "ocr": "reference"},
                        "env": {},
                        "prehooks": [
                            {
                                "type": "pyslam_ingest",
                                "tumGlob": "pyslam/*.txt",
                                "alignMode": "auto",
                                "replaceExisting": True,
                            }
                        ],
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

    baseline_json = out_dir / "baseline_reference" / "latest.json"
    offline_json = out_dir / "slam_offline_pyslam" / "latest.json"
    assert baseline_json.exists()
    assert offline_json.exists()
    assert (out_dir / "summary.json").exists()

    baseline_payload = json.loads(baseline_json.read_text(encoding="utf-8-sig"))
    offline_payload = json.loads(offline_json.read_text(encoding="utf-8-sig"))
    baseline_rows = baseline_payload.get("rows", [])
    offline_rows = offline_payload.get("rows", [])
    assert isinstance(baseline_rows, list) and len(baseline_rows) == 1
    assert isinstance(offline_rows, list) and len(offline_rows) == 1

    baseline_cov = baseline_rows[0].get("slam_coverage")
    offline_cov = offline_rows[0].get("slam_coverage")
    assert float(offline_cov or 0.0) == 1.0
    assert offline_rows[0].get("slam_align_residual_p90") is not None
    assert baseline_cov in {None, 0, 0.0}

    latest_csv = out_dir / "latest.csv"
    assert latest_csv.exists()
    header = latest_csv.read_text(encoding="utf-8-sig").splitlines()[0]
    assert "slam_coverage" in header
    assert "slam_align_residual_p90" in header

