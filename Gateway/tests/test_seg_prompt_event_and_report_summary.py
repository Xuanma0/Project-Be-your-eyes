from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_seg_prompt_event_and_report_summary(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_seg_prompt_min"

    output_md = tmp_path / "report_seg_prompt.md"
    output_json = tmp_path / "report_seg_prompt.json"

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
    seg_prompt = payload.get("segPrompt", {})
    assert seg_prompt.get("present") is True
    assert int(seg_prompt.get("textCharsTotal", 0)) == 26
    assert int(seg_prompt.get("boxesTotal", 0)) == 1
    assert int(seg_prompt.get("pointsTotal", 0)) == 2
    assert seg_prompt.get("promptVersion") == "v1"

    inference = payload.get("inference", {})
    seg = inference.get("seg", {})
    assert seg.get("promptPresent") is True
    assert int(seg.get("promptTextCharsTotal", 0)) == 26
    assert seg.get("promptVersion") == "v1"
