from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _run_report(gateway_dir: Path, run_package: Path, out_json: Path, out_md: Path) -> subprocess.CompletedProcess[str]:
    script = gateway_dir / "scripts" / "report_run.py"
    return subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_package),
            "--output",
            str(out_md),
            "--output-json",
            str(out_json),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )


def test_report_run_includes_pov_metrics_for_pov_fixture(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "pov_ir_v1_min"
    run_pkg = tmp_path / "run_pkg_pov"
    shutil.copytree(fixture_src, run_pkg)

    ingest_script = gateway_dir / "scripts" / "ingest_pov_ir.py"
    pov_ir_path = run_pkg / "pov" / "pov_ir_v1.json"
    ingest_result = subprocess.run(
        [
            sys.executable,
            str(ingest_script),
            "--run-package",
            str(run_pkg),
            "--pov-ir",
            str(pov_ir_path),
            "--strict",
            "1",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ingest_result.returncode == 0, f"stdout={ingest_result.stdout}\nstderr={ingest_result.stderr}"

    out_json = tmp_path / "report_pov.json"
    out_md = tmp_path / "report_pov.md"
    result = _run_report(gateway_dir, run_pkg, out_json, out_md)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))
    pov = payload.get("pov", {})
    counts = pov.get("counts", {})
    assert isinstance(pov, dict)
    assert bool(pov.get("present")) is True
    assert int(counts.get("decisions", 0)) == 2
    assert int(counts.get("events", 0)) == 1
    assert int(counts.get("highlights", 0)) == 1
    assert int(counts.get("tokens", 0)) == 1


def test_report_run_includes_pov_metrics_absent_for_non_pov_fixture(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    run_pkg = tests_dir / "fixtures" / "run_package_with_events_v1_min"

    out_json = tmp_path / "report_no_pov.json"
    out_md = tmp_path / "report_no_pov.md"
    result = _run_report(gateway_dir, run_pkg, out_json, out_md)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))
    pov = payload.get("pov", {})
    assert isinstance(pov, dict)
    assert bool(pov.get("present")) is False
