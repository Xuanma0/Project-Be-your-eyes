from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_report_run_from_run_package(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_min"
    output_md = tmp_path / "report_test.md"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_package_dir),
            "--output",
            str(output_md),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert output_md.exists()

    report = output_md.read_text(encoding="utf-8")
    assert "## Run Package Summary" in report
    assert "scenarioTag" in report
    assert "`byes_frame_received_total` delta sum" in report
    assert "`byes_e2e_latency_ms_count` delta" in report
