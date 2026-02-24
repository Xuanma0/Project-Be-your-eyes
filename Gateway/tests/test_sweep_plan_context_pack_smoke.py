from __future__ import annotations

import json
from pathlib import Path

from scripts import sweep_plan_context_pack


def test_sweep_plan_context_pack_smoke(tmp_path: Path) -> None:
    gateway_root = Path(__file__).resolve().parents[1]
    run_package = gateway_root / "tests" / "fixtures" / "run_package_with_risk_gt_and_pov_min"
    out_dir = tmp_path / "plan_ctx_sweep"

    payload = sweep_plan_context_pack.run_sweep(
        run_package=run_package,
        budgets=[256],
        modes=["seg_plus_pov_plus_risk"],
        out_dir=out_dir,
        port=19100,
    )

    latest_json = out_dir / "latest.json"
    latest_md = out_dir / "latest.md"
    assert latest_json.exists()
    assert latest_md.exists()

    loaded = json.loads(latest_json.read_text(encoding="utf-8-sig"))
    assert loaded.get("schemaVersion") == "byes.plan_context_pack.sweep.v1"
    rows = loaded.get("rows", [])
    assert isinstance(rows, list)
    assert len(rows) == 1
    recommendation = loaded.get("recommendation", {})
    assert isinstance(recommendation, dict)
    best = recommendation.get("best", {})
    assert isinstance(best, dict)
    assert best.get("maxChars") == 256
    assert best.get("mode") == "seg_plus_pov_plus_risk"

    assert payload.get("recommendation", {}).get("best", {}).get("maxChars") == 256
