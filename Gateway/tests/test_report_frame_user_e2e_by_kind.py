from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_frame_user_e2e_by_kind_summary(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_frame_user_e2e_kinds_min"
    run_pkg = tmp_path / "frame_user_e2e_kinds_run_pkg"
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
    user_e2e = report.get("frameUserE2E", {})
    assert isinstance(user_e2e, dict)
    assert bool(user_e2e.get("present")) is True
    by_kind = user_e2e.get("byKind", {})
    assert isinstance(by_kind, dict)

    tts_bucket = by_kind.get("tts", {})
    assert isinstance(tts_bucket, dict)
    assert float(tts_bucket.get("coverageRatio", 0.0) or 0.0) == 0.5
    tts_total = tts_bucket.get("totalMs", {})
    assert int(tts_total.get("count", 0) or 0) == 1
    assert int(tts_total.get("p90", 0) or 0) == 90
    assert int(tts_total.get("max", 0) or 0) == 90

    ar_bucket = by_kind.get("ar", {})
    assert isinstance(ar_bucket, dict)
    assert float(ar_bucket.get("coverageRatio", 0.0) or 0.0) == 0.5
    ar_total = ar_bucket.get("totalMs", {})
    assert int(ar_total.get("count", 0) or 0) == 1
    assert int(ar_total.get("p90", 0) or 0) == 160
    assert int(ar_total.get("max", 0) or 0) == 160

    tts_summary = user_e2e.get("tts", {})
    assert isinstance(tts_summary, dict)
    assert int(tts_summary.get("count", 0) or 0) == 1
    assert int(tts_summary.get("p90", 0) or 0) == 90
    assert int(tts_summary.get("max", 0) or 0) == 90
