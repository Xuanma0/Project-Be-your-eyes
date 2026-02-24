from __future__ import annotations

from byes.inference.prompt_budget import pack_prompt


def test_prompt_budget_packer_applies_truncation_and_stats() -> None:
    prompt = {
        "targets": [f"label{i}" for i in range(12)],
        "text": "x" * 400,
        "boxes": [[0, 0, 10, 10], [1, 1, 11, 11], [2, 2, 12, 12], [3, 3, 13, 13], [4, 4, 14, 14]],
        "points": [{"x": float(i), "y": float(i), "label": 1} for i in range(10)],
        "meta": {"promptVersion": "v1"},
    }
    packed, stats = pack_prompt(
        prompt,
        budget={
            "maxChars": 128,
            "maxTargets": 8,
            "maxBoxes": 4,
            "maxPoints": 8,
            "mode": "targets_text_boxes_points",
        },
    )

    assert isinstance(packed, dict)
    assert isinstance(stats, dict)
    assert stats.get("packed") is True
    trunc = stats.get("truncation", {})
    out = stats.get("out", {})
    in_stats = stats.get("in", {})
    assert isinstance(trunc, dict)
    assert isinstance(out, dict)
    assert isinstance(in_stats, dict)
    assert int(in_stats.get("targets", 0)) == 12
    assert int(out.get("targets", 0)) <= 8
    assert int(trunc.get("targetsDropped", 0)) >= 4
    assert int(out.get("textChars", 0)) <= 128
    assert int(trunc.get("textCharsDropped", 0)) > 0
    assert int(out.get("boxes", 0)) <= 4
    assert int(out.get("points", 0)) <= 8
    assert int(out.get("charsTotal", 0)) <= 128
