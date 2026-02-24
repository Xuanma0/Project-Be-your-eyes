from __future__ import annotations

import json
from pathlib import Path

from scripts.run_regression_suite import run_suite


def test_contract_suite_plan_request_gate_passes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gateway_root = repo_root / "Gateway"
    suite_path = gateway_root / "regression" / "suites" / "contract_suite.json"
    baseline_path = gateway_root / "regression" / "baselines" / "baseline.json"
    out_path = tmp_path / "contract_plan_request_gate.json"

    result, exit_code = run_suite(
        suite_path=suite_path,
        out_path=out_path,
        baseline_path=baseline_path,
        fail_on_drop=True,
        fail_on_critical_fn=True,
        write_baseline=False,
    )
    assert exit_code == 0, json.dumps(result, ensure_ascii=False)
    runs = result.get("runs", [])
    assert isinstance(runs, list)
    row = next((item for item in runs if str(item.get("id", "")) == "fixture_with_plan_request_contract"), None)
    assert isinstance(row, dict)
    seg_lint = row.get("segLint", {})
    assert isinstance(seg_lint, dict)
    assert bool(seg_lint.get("planRequestEventsPresent")) is True
    assert bool(seg_lint.get("planRequestSchemaOk")) is True
