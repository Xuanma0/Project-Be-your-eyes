from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_ingest_pov_ir_to_events_v1(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "pov_ir_v1_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    pov_ir_path = run_pkg / "pov" / "pov_ir_v1.json"
    ingest_script = gateway_dir / "scripts" / "ingest_pov_ir.py"

    result = subprocess.run(
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
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "warnings: 0" in result.stdout

    pov_obj = json.loads(pov_ir_path.read_text(encoding="utf-8-sig"))
    expected_count = (
        len(pov_obj.get("decisionPoints", []))
        + len(pov_obj.get("events", []))
        + len(pov_obj.get("highlights", []))
        + len(pov_obj.get("tokens", []))
    )

    events_path = run_pkg / "events" / "events_v1.jsonl"
    rows = []
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    assert len(rows) == expected_count
    names = {str(row.get("name", "")) for row in rows}
    assert "pov.decision" in names
    assert "pov.event" in names
    assert "pov.highlight" in names
    assert "pov.token" in names
    for row in rows:
        assert row.get("schemaVersion") == "byes.event.v1"
        assert row.get("component") == "pov-compiler"
        assert row.get("category") == "pov"
