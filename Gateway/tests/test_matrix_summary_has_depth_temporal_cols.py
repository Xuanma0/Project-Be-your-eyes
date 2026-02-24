from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_matrix_summary_has_depth_temporal_cols(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "run_dataset_benchmark.py"

    src_pkg = tests_dir / "fixtures" / "run_package_with_depth_temporal_min"
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
                        "name": "da3_fixture_depth_temporal",
                        "services": {"seg": "reference", "depth": "da3", "ocr": "reference"},
                        "env": {
                            "BYES_ENABLE_DEPTH": "1",
                            "BYES_SERVICE_DEPTH_HTTP_DOWNSTREAM": "da3",
                            "BYES_DA3_MODE": "fixture",
                            "BYES_SERVICE_DEPTH_HTTP_REF_VIEW_STRATEGY": "auto_ref",
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
    assert "depthJitterP90(p90)" in text
    assert "depthFlickerMean(mean)" in text
    assert "depthScaleDriftP90(p90)" in text
    assert "depthRefViewDiversity(mean)" in text
