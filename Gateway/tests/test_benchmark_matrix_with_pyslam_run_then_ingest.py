from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_benchmark_matrix_with_pyslam_run_then_ingest(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "run_dataset_benchmark.py"

    src_pkg = tests_dir / "fixtures" / "run_package_with_pyslam_run_fixture_min"
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
                        "name": "slam_offline_pyslam_run",
                        "services": {"seg": "reference", "depth": "reference", "ocr": "reference"},
                        "env": {},
                        "prehooks": [
                            {
                                "type": "pyslam_run",
                                "mode": "fixture",
                                "thenIngest": True,
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

    baseline_payload = json.loads((out_dir / "baseline_reference" / "latest.json").read_text(encoding="utf-8-sig"))
    offline_payload = json.loads((out_dir / "slam_offline_pyslam_run" / "latest.json").read_text(encoding="utf-8-sig"))
    summary_payload = json.loads((out_dir / "summary.json").read_text(encoding="utf-8-sig"))

    baseline_rows = baseline_payload.get("rows", [])
    offline_rows = offline_payload.get("rows", [])
    assert isinstance(baseline_rows, list) and len(baseline_rows) == 1
    assert isinstance(offline_rows, list) and len(offline_rows) == 1
    assert baseline_rows[0].get("slam_coverage") in {None, 0, 0.0}
    assert float(offline_rows[0].get("slam_coverage") or 0.0) == 1.0
    assert offline_rows[0].get("slam_align_residual_p90") is not None
    assert str(offline_payload.get("services", "")).endswith("+pyslam_run")

    profiles = summary_payload.get("profiles", [])
    assert isinstance(profiles, list)
    profile_map = {str(item.get("name")): item for item in profiles if isinstance(item, dict)}
    assert "slam_offline_pyslam_run" in profile_map
    metrics = profile_map["slam_offline_pyslam_run"].get("metrics", {})
    metrics = metrics if isinstance(metrics, dict) else {}
    slam_cov = metrics.get("slam_coverage", {})
    slam_cov = slam_cov if isinstance(slam_cov, dict) else {}
    assert float(slam_cov.get("mean") or 0.0) == 1.0

