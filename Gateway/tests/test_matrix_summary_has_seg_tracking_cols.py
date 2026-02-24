from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_matrix_summary_has_seg_tracking_cols(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "run_dataset_benchmark.py"

    src_pkg = tests_dir / "fixtures" / "run_package_with_sam3_tracking_fixture_seg_min"
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
                        "env": {"BYES_ENABLE_SEG": "1"},
                    },
                    {
                        "name": "sam3_tracking_fixture",
                        "services": {"seg": "sam3", "depth": "reference", "ocr": "reference"},
                        "env": {
                            "BYES_ENABLE_SEG": "1",
                            "BYES_SAM3_MODE": "fixture",
                            "BYES_SERVICE_SEG_HTTP_TRACKING": "1",
                            "BYES_SEG_TRACKING": "1",
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
    assert "segTrackCoverage(mean)" in text
    assert "segTracksTotal(mean)" in text
    assert "segIdSwitchCount(mean)" in text
