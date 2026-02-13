from __future__ import annotations

import json
from pathlib import Path

from scripts import ablate_planner


def test_ablate_planner_smoke(tmp_path: Path) -> None:
    run_package = Path(__file__).resolve().parent / "fixtures" / "run_package_with_risk_gt_and_pov_min"
    out_dir = tmp_path / "ablate"

    def _fake_evaluator(*, run_package: Path, provider: str, prompt_version: str, budget_tokens: int, out_dir: Path):
        return {
            "provider": provider,
            "promptVersion": prompt_version,
            "maxTokensApprox": int(budget_tokens),
            "maxChars": int(min(4000, int(budget_tokens) * 4)),
            "context": {"tokenApprox": int(budget_tokens), "charsTotal": int(budget_tokens) * 4, "decisions": 2, "highlights": 1, "tokens": 1},
            "metrics": {
                "qualityScore": 90.0 if int(budget_tokens) == 128 else 88.0,
                "critical_fn": 0,
                "missCriticalCount": 0,
                "riskLatencyP90": 100,
                "plan_latency_p90": 40 if int(budget_tokens) == 128 else 50,
                "confirm_timeouts": 0,
                "confirm_requests": 1,
                "overcautious_rate": 0.0,
                "guardrail_override_rate": 0.3,
            },
            "notes": "ok",
            "stdout": "",
        }

    payload, code = ablate_planner.run_ablation(
        run_package=run_package,
        providers=["reference"],
        prompt_versions=["v1"],
        budgets=[128, 256],
        out_dir=out_dir,
        fail_on_critical_fn=False,
        evaluator=_fake_evaluator,
    )

    assert code == 0
    latest_json = out_dir / "latest.json"
    latest_md = out_dir / "latest.md"
    assert latest_json.exists()
    assert latest_md.exists()

    parsed = json.loads(latest_json.read_text(encoding="utf-8-sig"))
    rows = parsed.get("rows", [])
    assert len(rows) == 2
    recommendation = parsed.get("recommendation", {})
    best = recommendation.get("best", {})
    assert best.get("maxTokensApprox") in [128, 256]
