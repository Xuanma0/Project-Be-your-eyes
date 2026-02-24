from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_has_frame_e2e_summary(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_frame_e2e_min"
    run_pkg = tmp_path / "frame_e2e_run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    script = gateway_dir / "scripts" / "report_run.py"
    out_md = tmp_path / "report.md"
    out_json = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_pkg),
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
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    report = json.loads(out_json.read_text(encoding="utf-8-sig"))
    frame_e2e = report.get("frameE2E", {})
    assert isinstance(frame_e2e, dict)
    assert bool(frame_e2e.get("present")) is True
    total = frame_e2e.get("totalMs", {})
    assert isinstance(total, dict)
    assert int(total.get("count", 0) or 0) == 2
    assert int(total.get("p90", 0) or 0) == 120
    assert int(total.get("max", 0) or 0) == 120
    parts = frame_e2e.get("partsMs", {})
    assert isinstance(parts, dict)
    seg = parts.get("segMs", {})
    assert isinstance(seg, dict)
    assert int(seg.get("p90", 0) or 0) == 40
