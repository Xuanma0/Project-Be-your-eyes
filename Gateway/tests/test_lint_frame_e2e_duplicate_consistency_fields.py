from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.lint_run_package import lint_run_package


def test_lint_frame_e2e_duplicate_and_consistency_fields(tmp_path: Path) -> None:
    fixture_src = Path(__file__).resolve().parent / "fixtures" / "run_package_with_frame_e2e_min"
    run_pkg = tmp_path / "frame_e2e_lint"
    shutil.copytree(fixture_src, run_pkg)

    events_path = run_pkg / "events" / "events_v1.jsonl"
    duplicate_row = {
        "schemaVersion": "byes.event.v1",
        "tsMs": 1713001000310,
        "runId": "fixture-frame-e2e-min",
        "frameSeq": 2,
        "component": "gateway",
        "category": "frame",
        "name": "frame.e2e",
        "phase": "result",
        "status": "ok",
        "latencyMs": 10,
        "payload": {
            "schemaVersion": "frame.e2e.v1",
            "runId": "fixture-frame-e2e-min",
            "frameSeq": 2,
            "t0Ms": 1713001000300,
            "t1Ms": 1713001000310,
            "totalMs": 10,
            "partsMs": {"segMs": 8, "riskMs": 8, "planMs": 8, "executeMs": None, "confirmMs": None},
            "present": {"seg": True, "risk": True, "plan": True, "execute": False, "confirm": False},
        },
    }
    with events_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(duplicate_row, ensure_ascii=False) + "\n")

    code, summary = lint_run_package(run_pkg, strict=False, quiet=True)
    assert code == 0
    assert int(summary.get("frameE2eDuplicateCount", 0) or 0) >= 1
    assert int(summary.get("frameE2ePartsSumGtTotalCount", 0) or 0) >= 1
