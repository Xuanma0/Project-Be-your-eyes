from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _count_pyslam_pose_events(events_path: Path) -> int:
    count = 0
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            row = json.loads(line)
            if str(row.get("name", "")).strip().lower() != "slam.pose":
                continue
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            model = str(payload.get("model", "")).strip().lower()
            if model.startswith("pyslam-") or model == "pyslam":
                count += 1
    return count


def test_ingest_replace_existing_idempotent(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_pyslam_dir_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    script = gateway_dir / "scripts" / "ingest_pyslam_tum.py"
    tum_path = run_pkg / "pyslam" / "byes_traj_online.txt"
    events_path = run_pkg / "events" / "events_v1.jsonl"

    first = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_pkg),
            "--tum",
            str(tum_path),
            "--replace-existing",
            "1",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, f"stdout={first.stdout}\nstderr={first.stderr}"
    count_after_first = _count_pyslam_pose_events(events_path)
    assert count_after_first == 3

    second = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-package",
            str(run_pkg),
            "--tum",
            str(tum_path),
            "--replace-existing",
            "1",
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, f"stdout={second.stdout}\nstderr={second.stderr}"
    count_after_second = _count_pyslam_pose_events(events_path)
    assert count_after_second == count_after_first
    assert "removedExisting:" in second.stdout

