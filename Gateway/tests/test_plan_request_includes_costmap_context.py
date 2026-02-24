from __future__ import annotations

from byes.plan_pipeline import build_planner_request


def test_plan_request_includes_costmap_context() -> None:
    context_pack = {
        "budget": {"maxChars": 2000, "maxTokensApprox": 500, "mode": "decisions_plus_highlights"},
        "text": {"prompt": "[POV] move ahead"},
        "stats": {"out": {"tokenApprox": 10}, "truncation": {"charsDropped": 0}},
    }
    risk_summary = {"riskLevel": "low", "hazardsCount": 0, "hazardsTop": []}
    constraints = {"allowConfirm": True, "allowHaptic": False, "maxActions": 3}
    seg_context = {
        "text": {"promptFragment": "[SEG] person(0.9)"},
        "stats": {"out": {"tokenApprox": 5}, "truncation": {"segmentsDropped": 0, "charsDropped": 0}},
    }
    slam_context = {"text": {"promptFragment": "[SLAM] state=tracking"}}
    costmap_context = {
        "text": {"promptFragment": "[COSTMAP] hotspots: left-near:255"},
        "stats": {"out": {"charsTotal": 34}, "truncation": {"hotspotsDropped": 0}},
    }

    payload = build_planner_request(
        run_id="fixture-costmap-min",
        frame_seq=2,
        context_pack=context_pack,
        risk_summary=risk_summary,
        constraints=constraints,
        planner_provider="http",
        seg_context=seg_context,
        slam_context=slam_context,
        costmap_context=costmap_context,
        plan_context_pack=None,
    )

    contexts = payload.get("contexts", {})
    contexts = contexts if isinstance(contexts, dict) else {}
    costmap = contexts.get("costmap", {})
    costmap = costmap if isinstance(costmap, dict) else {}
    assert bool(costmap.get("present")) is True
    assert str(costmap.get("promptFragment", "")).startswith("[COSTMAP]")

    meta = payload.get("meta", {})
    meta = meta if isinstance(meta, dict) else {}
    assert bool(meta.get("costmapIncluded")) is True
    assert int(meta.get("costmapChars", 0) or 0) > 0

    compat = payload.get("costmapContext", {})
    compat = compat if isinstance(compat, dict) else {}
    text = compat.get("text", {})
    text = text if isinstance(text, dict) else {}
    assert str(text.get("promptFragment", "")).startswith("[COSTMAP]")
