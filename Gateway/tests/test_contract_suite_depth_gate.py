from __future__ import annotations

import json
from pathlib import Path

from scripts.run_regression_suite import run_suite


def test_contract_suite_depth_gate_passes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gateway_root = repo_root / "Gateway"
    suite_path = gateway_root / "regression" / "suites" / "contract_suite.json"
    baseline_path = gateway_root / "regression" / "baselines" / "baseline.json"
    out_path = tmp_path / "contract_depth_gate_test.json"

    result, exit_code = run_suite(
        suite_path=suite_path,
        out_path=out_path,
        baseline_path=baseline_path,
        fail_on_drop=True,
        fail_on_critical_fn=True,
        write_baseline=False,
    )

    assert exit_code == 0, json.dumps(result, ensure_ascii=False)
    meta = result.get("meta", {})
    assert isinstance(meta, dict)
    assert bool(meta.get("contractsOk")) is True

    runs = result.get("runs", [])
    assert isinstance(runs, list)
    depth_row = next((row for row in runs if str(row.get("id", "")) == "fixture_with_depth_gt_contract"), None)
    assert isinstance(depth_row, dict)
    seg_lint = depth_row.get("segLint", {})
    assert isinstance(seg_lint, dict)
    assert bool(seg_lint.get("depthEventsPresent")) is True
    assert bool(seg_lint.get("depthPayloadSchemaOk")) is True

