from __future__ import annotations

import json
from pathlib import Path

from scripts.run_regression_suite import run_suite


def test_contract_suite_ocr_gate_passes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gateway_root = repo_root / "Gateway"
    suite_path = gateway_root / "regression" / "suites" / "contract_suite.json"
    baseline_path = gateway_root / "regression" / "baselines" / "baseline.json"
    out_path = tmp_path / "contract_ocr_gate_test.json"

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
    row = next((item for item in runs if str(item.get("id", "")) == "fixture_with_ocr_gt_contract"), None)
    assert isinstance(row, dict)
    lint = row.get("segLint", {})
    assert isinstance(lint, dict)
    assert bool(lint.get("ocrEventsPresent")) is True
    assert bool(lint.get("ocrPayloadSchemaOk")) is True
