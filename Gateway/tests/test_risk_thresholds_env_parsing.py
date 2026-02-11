from __future__ import annotations

from services.inference_service.providers.heuristic_risk import RiskThresholds


def test_risk_thresholds_defaults_from_env_empty(monkeypatch) -> None:
    for key in (
        "BYES_RISK_DEPTH_OBS_WARN",
        "BYES_RISK_DEPTH_OBS_CRIT",
        "BYES_RISK_DEPTH_DROPOFF_DELTA",
        "BYES_RISK_OBS_WARN",
        "BYES_RISK_OBS_CRIT",
        "BYES_RISK_DROPOFF_PEAK",
        "BYES_RISK_DROPOFF_CONTRAST",
        "BYES_RISK_EDGE_DENSITY_WARN",
        "BYES_RISK_EDGE_DENSITY_CRIT",
    ):
        monkeypatch.delenv(key, raising=False)

    thresholds = RiskThresholds.from_env()
    assert thresholds.depth_obs_warn == 1.0
    assert thresholds.depth_obs_crit == 0.6
    assert thresholds.depth_dropoff_delta == 0.8
    assert thresholds.obs_warn == 0.14
    assert thresholds.obs_crit == 0.24
    assert thresholds.dropoff_peak == 28.0
    assert thresholds.dropoff_contrast == 0.2


def test_risk_thresholds_override_and_clamp(monkeypatch) -> None:
    monkeypatch.setenv("BYES_RISK_DEPTH_OBS_WARN", "0.75")
    monkeypatch.setenv("BYES_RISK_DEPTH_OBS_CRIT", "0.55")
    monkeypatch.setenv("BYES_RISK_DEPTH_DROPOFF_DELTA", "0.6")
    monkeypatch.setenv("BYES_RISK_OBS_WARN", "0.18")
    monkeypatch.setenv("BYES_RISK_OBS_CRIT", "0.31")
    monkeypatch.setenv("BYES_RISK_DROPOFF_PEAK", "40")
    monkeypatch.setenv("BYES_RISK_DROPOFF_CONTRAST", "1.5")

    thresholds = RiskThresholds.from_env()
    assert thresholds.depth_obs_warn == 0.75
    assert thresholds.depth_obs_crit == 0.55
    assert thresholds.depth_dropoff_delta == 0.6
    assert thresholds.obs_warn == 0.18
    assert thresholds.obs_crit == 0.31
    assert thresholds.dropoff_peak == 40.0
    assert thresholds.dropoff_contrast == 1.0

    merged = thresholds.with_overrides({"depthObsCrit": 0.45, "obsCrit": 0.22, "dropoffContrast": 0.15})
    assert merged.depth_obs_crit == 0.45
    assert merged.obs_crit == 0.22
    assert merged.dropoff_contrast == 0.15
