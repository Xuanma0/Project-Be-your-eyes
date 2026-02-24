from __future__ import annotations

import json
from pathlib import Path

from scripts import sweep_plan_context_pack


def test_sweep_plan_context_pack_includes_frame_e2e_if_present(tmp_path: Path) -> None:
    gateway_root = Path(__file__).resolve().parents[1]
    run_package = gateway_root / "tests" / "fixtures" / "run_package_with_frame_e2e_min"
    out_dir = tmp_path / "plan_ctx_sweep_frame_e2e"

    payload = sweep_plan_context_pack.run_sweep(
        run_package=run_package,
        budgets=[256],
        modes=["risk_only"],
        out_dir=out_dir,
        port=19100,
    )

    latest_json = out_dir / "latest.json"
    assert latest_json.exists()
    loaded = json.loads(latest_json.read_text(encoding="utf-8-sig"))
    rows = loaded.get("rows", [])
    assert isinstance(rows, list)
    assert len(rows) == 1

    metrics = rows[0].get("metrics", {})
    assert isinstance(metrics, dict)
    assert "frameE2EP90" in metrics
    assert int(metrics.get("frameE2EP90", 0) or 0) > 0

    recommendation = loaded.get("recommendation", {})
    assert isinstance(recommendation, dict)
    assert "best" in recommendation
    assert payload.get("recommendation", {}).get("best", {}).get("maxChars") == 256
