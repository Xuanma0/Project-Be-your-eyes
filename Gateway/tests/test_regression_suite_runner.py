from __future__ import annotations

import json
from pathlib import Path

from scripts.run_regression_suite import run_suite


def test_regression_suite_runner_outputs_json(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    suite_path = gateway_dir / "regression" / "suites" / "baseline_suite.json"
    out_path = tmp_path / "suite_out.json"

    result, exit_code = run_suite(
        suite_path=suite_path,
        out_path=out_path,
        baseline_path=None,
        fail_on_drop=False,
        write_baseline=False,
    )

    assert exit_code == 0, result
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8-sig"))
    runs = payload.get("runs", [])
    assert isinstance(runs, list) and len(runs) >= 2
    first = runs[0]
    assert "qualityScore" in first
    assert "safetyBehavior" in first
    assert "eventSchema" in first
    assert "confirmTimeouts" in first["safetyBehavior"]


def test_regression_suite_runner_detects_drop(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    suite_path = gateway_dir / "regression" / "suites" / "baseline_suite.json"
    out_path = tmp_path / "suite_out_drop.json"
    baseline_path = tmp_path / "baseline.json"

    baseline_payload = {
        "suiteName": "baseline",
        "generatedAtMs": 0,
        "runs": [
            {"id": "fixture_with_gt", "qualityScore": 99.0},
            {"id": "fixture_with_safety", "qualityScore": 99.0},
            {"id": "fixture_events_v1", "qualityScore": 99.0},
        ],
    }
    baseline_path.write_text(json.dumps(baseline_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result, exit_code = run_suite(
        suite_path=suite_path,
        out_path=out_path,
        baseline_path=baseline_path,
        fail_on_drop=True,
        write_baseline=False,
    )

    assert exit_code == 1
    failures = result.get("failures", [])
    assert isinstance(failures, list)
    assert any("qualityScore drop" in item for item in failures)
