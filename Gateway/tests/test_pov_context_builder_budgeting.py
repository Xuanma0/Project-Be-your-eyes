from __future__ import annotations

import json
import math
from pathlib import Path

from byes.pov_context import build_context_pack, finalize_context_pack_text, render_context_text


def _load_fixture_pov_ir() -> dict:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "pov_ir_v1_min" / "pov" / "pov_ir_v1.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    assert isinstance(payload, dict)
    return payload


def test_pov_context_builder_budgeting_deterministic_and_token_approx() -> None:
    pov_ir = _load_fixture_pov_ir()
    budget = {"maxChars": 220, "maxTokensApprox": 55}

    pack_a = build_context_pack(pov_ir, budget=budget, mode="full")
    pack_b = build_context_pack(pov_ir, budget=budget, mode="full")
    assert pack_a == pack_b

    text = render_context_text(pack_a)
    pack_a = finalize_context_pack_text(pack_a, text, generated_at_ms=1700000000000)
    assert len(text["prompt"]) <= budget["maxChars"]

    out_stats = pack_a.get("stats", {}).get("out", {})
    chars_total = int(out_stats.get("charsTotal", 0) or 0)
    token_approx = int(out_stats.get("tokenApprox", 0) or 0)
    assert token_approx == int(math.ceil(chars_total / 4.0)) if chars_total > 0 else token_approx == 0


def test_pov_context_builder_small_budget_truncates_content() -> None:
    pov_ir = _load_fixture_pov_ir()
    pack = build_context_pack(pov_ir, budget={"maxChars": 80, "maxTokensApprox": 20}, mode="full")
    truncation = pack.get("stats", {}).get("truncation", {})
    dropped_total = int(truncation.get("decisionsDropped", 0) or 0) + int(truncation.get("highlightsDropped", 0) or 0) + int(
        truncation.get("tokensDropped", 0) or 0
    )
    assert dropped_total >= 1

    text = render_context_text(pack)
    assert len(text.get("prompt", "")) <= 80
