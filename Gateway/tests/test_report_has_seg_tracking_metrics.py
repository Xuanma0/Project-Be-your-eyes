from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_report_has_seg_tracking_metrics(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_sam3_tracking_fixture_seg_min"

    output_md = tmp_path / "report_seg_tracking.md"
    output_json = tmp_path / "report_seg_tracking.json"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_package_dir),
            "--output",
            str(output_md),
            "--output-json",
            str(output_json),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    payload = json.loads(output_json.read_text(encoding="utf-8-sig"))
    quality = payload.get("quality", {})
    seg_tracking = quality.get("segTracking", {})
    assert isinstance(seg_tracking, dict)
    assert bool(seg_tracking.get("present")) is True
    assert float(seg_tracking.get("trackCoverage", 0.0)) > 0.0
    assert int(seg_tracking.get("tracksTotal", 0) or 0) >= 1
    assert "idSwitchCount" in seg_tracking
