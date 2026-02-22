from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_ingest_pyslam_tum_writes_slam_pose_events(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_pyslam_tum_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    script = gateway_dir / "scripts" / "ingest_pyslam_tum.py"
    tum_path = run_pkg / "pyslam" / "byes_traj.tum"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_pkg),
            "--tum",
            str(tum_path),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "matched: 2" in result.stdout
    assert "written: 2" in result.stdout

    events_path = run_pkg / "events" / "events_v1.jsonl"
    rows = []
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    assert len(rows) == 2
    frame_seq_set = {int(row.get("frameSeq", 0) or 0) for row in rows}
    assert frame_seq_set == {1, 2}
    for row in rows:
        assert row.get("schemaVersion") == "byes.event.v1"
        assert row.get("name") == "slam.pose"
        assert row.get("category") == "tool"
        payload = row.get("payload")
        assert isinstance(payload, dict)
        assert payload.get("schemaVersion") == "byes.slam_pose.v1"
        assert payload.get("backend") == "offline"
        assert payload.get("model") == "pyslam"
        pose = payload.get("pose")
        assert isinstance(pose, dict)
        assert isinstance(pose.get("t"), list) and len(pose.get("t")) == 3
        assert isinstance(pose.get("q"), list) and len(pose.get("q")) == 4
