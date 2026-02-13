from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _parse_summary_value(stdout: str, key: str) -> str | None:
    prefix = f"{key}:"
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def test_lint_pov_ir_fixture_strict_passes_and_reports_pov_fields(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "lint_run_package.py"
    ingest_script = gateway_dir / "scripts" / "ingest_pov_ir.py"
    fixture_src = tests_dir / "fixtures" / "pov_ir_v1_min"
    run_package = tmp_path / "run_pkg_pov_lint"
    shutil.copytree(fixture_src, run_package)

    ingest = subprocess.run(
        [
            sys.executable,
            str(ingest_script),
            "--run-package",
            str(run_package),
            "--pov-ir",
            str(run_package / "pov" / "pov_ir_v1.json"),
            "--strict",
            "1",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ingest.returncode == 0, f"stdout={ingest.stdout}\nstderr={ingest.stderr}"

    result = subprocess.run(
        [sys.executable, str(script), "--run-package", str(run_package), "--strict"],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert _parse_summary_value(result.stdout, "povIrPresent") == "1"
    assert _parse_summary_value(result.stdout, "povIrDecisions") == "2"
    assert _parse_summary_value(result.stdout, "povIrSchemaOk") == "2"
    assert _parse_summary_value(result.stdout, "povEventsCount") is not None


def test_lint_pov_ir_missing_file_strict_fails(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "lint_run_package.py"
    fixture_src = tests_dir / "fixtures" / "pov_ir_v1_min"
    run_pkg = tmp_path / "run_pkg_missing_pov"
    shutil.copytree(fixture_src, run_pkg)
    (run_pkg / "pov" / "pov_ir_v1.json").unlink()

    result = subprocess.run(
        [sys.executable, str(script), "--run-package", str(run_pkg), "--strict"],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "povIrJson missing" in result.stdout
