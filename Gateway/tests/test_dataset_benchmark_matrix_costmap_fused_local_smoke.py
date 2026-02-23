from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_dataset_benchmark_matrix_includes_costmap_fused_columns(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "run_dataset_benchmark.py"

    src_pkg = tests_dir / "fixtures" / "run_package_with_costmap_fused_min"
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
                        "name": "costmap_local",
                        "services": {"seg": "reference", "depth": "reference", "ocr": "reference"},
                        "env": {"BYES_ENABLE_COSTMAP": "1", "BYES_PLANNER_PROMPT_VERSION": "v4"},
                    },
                    {
                        "name": "costmap_fused_local",
                        "services": {"seg": "reference", "depth": "reference", "ocr": "reference"},
                        "env": {
                            "BYES_ENABLE_COSTMAP": "1",
                            "BYES_ENABLE_COSTMAP_FUSED": "1",
                            "BYES_PLANNER_PROMPT_VERSION": "v4",
                        },
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

    summary_md = out_dir / "summary.md"
    assert summary_md.exists()
    text = summary_md.read_text(encoding="utf-8-sig")
    assert "costmapFusedCoverage(mean)" in text
    assert "costmapFusedIouP90(p90)" in text
    assert "costmapFusedFlickerMean(mean)" in text

    latest_csv = out_dir / "latest.csv"
    header = latest_csv.read_text(encoding="utf-8-sig").splitlines()[0]
    assert "costmap_fused_coverage" in header
    assert "costmap_fused_iou_p90" in header
    assert "costmap_fused_flicker_rate_mean" in header
