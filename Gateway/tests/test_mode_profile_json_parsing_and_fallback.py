from __future__ import annotations

import pytest

from byes.mode_state import parse_mode_profile_json
from byes.scheduler import should_run_mode_target


def test_mode_profile_empty_string_falls_back_to_legacy_behavior() -> None:
    profile = parse_mode_profile_json("")
    assert profile is None
    assert should_run_mode_target(
        frame_seq=2,
        mode="walk",
        target="ocr",
        profile=profile,
        force_on_mode_change=False,
    )


def test_mode_profile_invalid_json_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_mode_profile_json("{bad json")


def test_mode_profile_uses_default_when_mode_missing() -> None:
    profile = parse_mode_profile_json(
        """
        {
          "default": {
            "risk": {"every_n_frames": 1},
            "ocr": {"every_n_frames": 4}
          },
          "read": {
            "ocr": {"every_n_frames": 1}
          }
        }
        """
    )
    assert profile is not None
    assert profile.stride_for("inspect", "ocr") == 4
    assert profile.stride_for("read_text", "ocr") == 1

