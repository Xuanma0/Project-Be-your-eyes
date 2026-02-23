from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_ingest_pyslam_relative_time_aligns_all_frames(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_pyslam_tum_relative_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    script = gateway_dir / "scripts" / "ingest_pyslam_tum.py"
    tum_path = run_pkg / "pyslam" / "online.txt"
    tolerance_ms = 50

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_pkg),
            "--tum",
            str(tum_path),
            "--tum-time-base",
            "auto",
            "--align-mode",
            "auto",
            "--tolerance-ms",
            str(tolerance_ms),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "matched: 3" in result.stdout
    assert "written: 3" in result.stdout

    events_path = run_pkg / "events" / "events_v1.jsonl"
    rows = []
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if line:
                rows.append(json.loads(line))

    assert len(rows) == 3
    assert [int(row.get("frameSeq", 0) or 0) for row in rows] == [1, 2, 3]
    for row in rows:
        payload = row.get("payload")
        assert isinstance(payload, dict)
        assert str(payload.get("model", "")) == "pyslam-online"

    ingest_summary_path = run_pkg / "events" / "slam_ingest_summary.json"
    summary = json.loads(ingest_summary_path.read_text(encoding="utf-8-sig"))
    assert int(summary.get("matched", 0) or 0) == 3
    residual = summary.get("residualMs", {})
    assert isinstance(residual, dict)
    residual_p90 = residual.get("p90")
    assert isinstance(residual_p90, int)
    assert residual_p90 <= tolerance_ms
