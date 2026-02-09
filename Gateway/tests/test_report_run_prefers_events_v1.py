from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_report_run_prefers_events_v1(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    script = gateway_dir / "scripts" / "report_run.py"
    run_package_dir = tests_dir / "fixtures" / "run_package_with_events_v1_min"

    output_md = tmp_path / "report_events_v1.md"
    output_json = tmp_path / "report_events_v1.json"

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
    event_schema = quality.get("eventSchema", {})
    safety = quality.get("safetyBehavior", {})
    confirm = safety.get("confirm", {})
    inference = payload.get("inference", {})
    inference_ocr = inference.get("ocr", {})
    inference_risk = inference.get("risk", {})

    assert event_schema.get("source") == "eventsV1Jsonl"
    assert str(event_schema.get("eventsV1Path", "")) == "events/events_v1.jsonl"
    assert int(event_schema.get("normalizedEvents", 0)) > 0
    assert int(confirm.get("timeouts", 0)) == 1
    assert int(confirm.get("missingResponseCount", 0)) == 1
    assert isinstance(inference_ocr, dict)
    assert isinstance(inference_risk, dict)
    assert "backend" in inference_ocr
    assert "backend" in inference_risk
