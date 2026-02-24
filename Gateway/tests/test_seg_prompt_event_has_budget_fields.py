from __future__ import annotations

from byes.inference.prompt_budget import pack_prompt
from main import GatewayApp


def test_seg_prompt_event_payload_contains_budget_out_truncation() -> None:
    prompt = {
        "targets": [f"t{i}" for i in range(10)],
        "text": "a" * 300,
        "boxes": [[0, 0, 10, 10], [1, 1, 11, 11], [2, 2, 12, 12], [3, 3, 13, 13], [4, 4, 14, 14]],
        "points": [{"x": 1.0, "y": 1.0, "label": 1}] * 9,
        "meta": {"promptVersion": "v1"},
    }
    budget = {"maxChars": 128, "maxTargets": 8, "maxBoxes": 4, "maxPoints": 8, "mode": "targets_text_boxes_points"}
    packed, stats = pack_prompt(prompt, budget=budget)
    assert isinstance(packed, dict)
    payload = GatewayApp._build_seg_prompt_payload(  # noqa: SLF001
        packed,
        backend="http",
        model="reference-seg-v1",
        endpoint="http://127.0.0.1:9003/seg",
        budget=budget,
        pack_stats=stats,
    )

    assert int(payload.get("targetsCount", 0)) >= 0
    assert "budget" in payload and isinstance(payload["budget"], dict)
    assert "out" in payload and isinstance(payload["out"], dict)
    assert "truncation" in payload and isinstance(payload["truncation"], dict)
    assert "complexity" in payload and isinstance(payload["complexity"], dict)
    assert payload.get("packed") is True
    trunc = payload["truncation"]
    assert int(trunc.get("targetsDropped", 0)) > 0
    assert int(trunc.get("textCharsDropped", 0)) > 0
