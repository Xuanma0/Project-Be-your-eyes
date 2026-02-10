from __future__ import annotations

from byes.hazards.taxonomy_v1 import normalize_hazard_kind, normalize_hazards


def test_hazard_taxonomy_alias_mapping() -> None:
    kind, warnings = normalize_hazard_kind("stair_down_edge")
    assert kind == "dropoff"
    assert any(str(item).startswith("alias:") for item in warnings)


def test_hazard_taxonomy_unknown_kind_warning() -> None:
    kind, warnings = normalize_hazard_kind("glass_wall")
    assert kind == "glass_wall"
    assert "unknown_kind:glass_wall" in warnings


def test_normalize_hazards_preserves_original_kind() -> None:
    rows, warnings = normalize_hazards([{"hazardKind": "ledge", "severity": "critical"}])
    assert rows
    assert rows[0]["hazardKind"] == "dropoff"
    assert rows[0]["originalKind"] == "ledge"
    assert any(str(item).startswith("alias:") for item in warnings)
