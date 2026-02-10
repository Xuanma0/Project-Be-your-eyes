from __future__ import annotations

from PIL import Image, ImageDraw

from services.inference_service.providers.heuristic_risk import HeuristicRiskProvider


def test_heuristic_risk_detects_structured_hazard(monkeypatch) -> None:
    monkeypatch.setenv("BYES_RISK_EDGE_DENSITY_WARN", "0.02")
    monkeypatch.setenv("BYES_RISK_EDGE_DENSITY_CRIT", "0.04")
    monkeypatch.setenv("BYES_RISK_DROPOFF_PEAK", "6")
    monkeypatch.setenv("BYES_RISK_MIN_EDGE_DENSITY", "0.005")
    image = Image.new("RGB", (320, 180), (220, 220, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 96, 319, 118], fill=(30, 30, 30))
    draw.rectangle([0, 119, 319, 179], fill=(0, 0, 0))
    for x in range(0, 320, 8):
        draw.line([(x, 98), (x, 118)], fill=(255, 255, 255), width=1)

    provider = HeuristicRiskProvider()
    result = provider.infer(image, frame_seq=2)
    hazards = result.get("hazards", [])
    kinds = {str(item.get("hazardKind")) for item in hazards if isinstance(item, dict)}
    assert kinds & {"obstacle_close", "stair_down"}


def test_heuristic_risk_reports_unknown_depth_for_dark_frame() -> None:
    image = Image.new("RGB", (320, 180), (4, 4, 4))
    provider = HeuristicRiskProvider()
    result = provider.infer(image, frame_seq=1)
    hazards = result.get("hazards", [])
    unknown = [item for item in hazards if isinstance(item, dict) and item.get("hazardKind") == "unknown_depth"]
    assert unknown
