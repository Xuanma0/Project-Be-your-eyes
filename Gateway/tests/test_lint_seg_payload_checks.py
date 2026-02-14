from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.lint_run_package import lint_run_package


def test_lint_seg_payload_checks(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_seg_gt_min"
    run_pkg = tmp_path / "run_pkg_seg_lint"
    shutil.copytree(fixture_src, run_pkg)

    events_path = run_pkg / "events" / "events_v1.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assert len(rows) >= 1
    payload = rows[0].get("payload", {})
    payload = payload if isinstance(payload, dict) else {}
    payload["imageWidth"] = 20
    payload["imageHeight"] = 20
    payload["segments"] = [{"label": "", "score": 1.5, "bbox": [21, 0, 10, 0]}]
    rows[0]["payload"] = payload
    events_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n", encoding="utf-8")

    code, summary = lint_run_package(run_pkg, strict=True, quiet=True)
    assert code == 0
    assert int(summary.get("segEventsPresent", 0)) == 1
    assert int(summary.get("segLines", 0)) >= 1
    assert int(summary.get("segPayloadSchemaOk", 0)) == 0
    assert int(summary.get("segBboxOutOfRangeCount", 0)) > 0
    assert int(summary.get("segScoreOutOfRangeCount", 0)) > 0
    assert int(summary.get("segEmptyLabelCount", 0)) > 0
