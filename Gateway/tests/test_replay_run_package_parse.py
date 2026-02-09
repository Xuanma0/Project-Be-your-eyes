from __future__ import annotations

from pathlib import Path

from scripts.replay_run_package import _load_frames_from_package, _load_manifest, _load_scenario_calls


def test_replay_run_package_parse() -> None:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "run_package_with_frames_min"
    manifest = _load_manifest(fixture_dir)
    frames = _load_frames_from_package(fixture_dir, manifest)
    scenario_calls = _load_scenario_calls(manifest)

    assert manifest["scenarioTag"] == "fixture_replay"
    assert len(frames) == 2
    assert [frame.seq for frame in frames] == [1, 2]
    assert frames[0].frame_path.exists()
    assert frames[1].frame_path.exists()
    assert len(scenario_calls) == 2
    assert scenario_calls[0].method == "POST"
    assert scenario_calls[0].path == "/api/dev/intent"
    assert scenario_calls[1].path == "/api/dev/crosscheck"
