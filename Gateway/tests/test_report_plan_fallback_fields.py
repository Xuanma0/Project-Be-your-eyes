from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_report_plan_fallback_fields(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_plan_llm_stub_min"
    run_pkg = tmp_path / "run_pkg"
    shutil.copytree(fixture_src, run_pkg)

    events_path = run_pkg / "events" / "events_v1.jsonl"
    rows = []
    for raw in events_path.read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        if str(row.get("name", "")).strip().lower() == "plan.generate":
            payload = row.get("payload", {})
            payload = payload if isinstance(payload, dict) else {}
            payload["fallbackUsed"] = True
            payload["fallbackReason"] = "timeout"
            payload["jsonValid"] = False
            row["payload"] = payload
        rows.append(row)
    events_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

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
    plan_quality = report.get("planQuality", {})
    assert plan_quality.get("fallbackUsed") is True
    assert plan_quality.get("fallbackReason") == "timeout"
    assert plan_quality.get("jsonValid") is False
