from __future__ import annotations

import subprocess
import sys
import zipfile
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


def test_report_run_from_run_package_zip(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_min"
    zip_path = tmp_path / "run_package_min.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in run_package_dir.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(run_package_dir))

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(zip_path),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    report_path = zip_path.parent / f"report_{zip_path.stem}.md"
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "## Run Package Summary" in report
    assert "source zip" in report.lower()
