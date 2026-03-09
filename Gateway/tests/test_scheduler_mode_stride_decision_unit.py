from __future__ import annotations

from byes.mode_state import parse_mode_profile_json
from byes.scheduler import should_run_mode_target


def _profile():
    profile = parse_mode_profile_json(
        """
        {
          "default": {
            "risk": {"every_n_frames": 1},
            "ocr": {"every_n_frames": 3},
            "depth": {"every_n_frames": 2}
          },
          "read": {
            "ocr": {"every_n_frames": 1}
          }
        }
        """
    )
    assert profile is not None
    return profile


def test_stride_rule_uses_frame_sequence_stably() -> None:
    profile = _profile()
    assert should_run_mode_target(frame_seq=1, mode="walk", target="ocr", profile=profile) is True
    assert should_run_mode_target(frame_seq=2, mode="walk", target="ocr", profile=profile) is False
    assert should_run_mode_target(frame_seq=3, mode="walk", target="ocr", profile=profile) is False
    assert should_run_mode_target(frame_seq=4, mode="walk", target="ocr", profile=profile) is True


def test_mode_specific_override_takes_precedence_over_default() -> None:
    profile = _profile()
    assert should_run_mode_target(frame_seq=2, mode="read_text", target="ocr", profile=profile) is True


def test_mode_change_force_runs_target_even_when_stride_would_skip() -> None:
    profile = parse_mode_profile_json('{"default":{"ocr":{"every_n_frames":10}}}')
    assert profile is not None
    assert (
        should_run_mode_target(
            frame_seq=2,
            mode="walk",
            target="ocr",
            profile=profile,
            force_on_mode_change=True,
        )
        is True
    )

