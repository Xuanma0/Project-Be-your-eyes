from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_report_inference_seg_from_events_v1(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_events_v1_inference_seg_min"

    output_md = tmp_path / "report_events_v1_infer_seg.md"
    output_json = tmp_path / "report_events_v1_infer_seg.json"

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
    inference = payload.get("inference", {})
    seg = inference.get("seg", {})

    assert seg == {
        "backend": "http",
        "model": "seg-mini-v2",
        "endpoint": "http://127.0.0.1:19120/seg",
    }
