from __future__ import annotations

import json
from pathlib import Path

from scripts.run_regression_suite import run_suite


def test_contract_suite_seg_gate_passes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gateway_root = repo_root / "Gateway"
    suite_path = gateway_root / "regression" / "suites" / "contract_suite.json"
    baseline_path = gateway_root / "regression" / "baselines" / "baseline.json"
    out_path = tmp_path / "contract_seg_gate_test.json"

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
    seg_row = next((row for row in runs if str(row.get("id", "")) == "fixture_with_seg_gt_contract"), None)
    assert isinstance(seg_row, dict)
    seg_lint = seg_row.get("segLint", {})
    assert isinstance(seg_lint, dict)
    assert bool(seg_lint.get("eventsPresent")) is True
    assert bool(seg_lint.get("payloadSchemaOk")) is True

    seg_prompt_row = next((row for row in runs if str(row.get("id", "")) == "fixture_with_seg_prompt_mask_contract"), None)
    assert isinstance(seg_prompt_row, dict)
    seg_prompt_lint = seg_prompt_row.get("segLint", {})
    assert isinstance(seg_prompt_lint, dict)
    assert bool(seg_prompt_lint.get("eventsPresent")) is True
    assert bool(seg_prompt_lint.get("payloadSchemaOk")) is True
    assert bool(seg_prompt_lint.get("promptEventsPresent")) is True
    assert bool(seg_prompt_lint.get("promptPayloadSchemaOk")) is True

    seg_prompt_budget_row = next(
        (row for row in runs if str(row.get("id", "")) == "fixture_with_seg_prompt_budget_contract"),
        None,
    )
    assert isinstance(seg_prompt_budget_row, dict)
    seg_prompt_budget_lint = seg_prompt_budget_row.get("segLint", {})
    assert isinstance(seg_prompt_budget_lint, dict)
    assert bool(seg_prompt_budget_lint.get("promptEventsPresent")) is True
    assert bool(seg_prompt_budget_lint.get("promptPayloadSchemaOk")) is True
    assert bool(seg_prompt_budget_lint.get("segPromptBudgetPresent")) is True
    assert bool(seg_prompt_budget_lint.get("segPromptTruncationPresent")) is True
    assert int(seg_prompt_budget_lint.get("segPromptPackedTrueCount", 0) or 0) > 0
