from __future__ import annotations

from pathlib import Path

from scripts.lint_run_package import lint_run_package


def test_lint_seg_prompt_payload_checks() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "run_package_with_seg_prompt_and_mask_gt_min"
    exit_code, summary = lint_run_package(fixture, strict=False, quiet=True)

    assert exit_code == 0
    assert int(summary.get("segPromptEventsPresent", 0)) == 1
    assert int(summary.get("segPromptLines", 0)) == 2
    assert int(summary.get("segPromptSchemaOk", 0)) == 2
    assert int(summary.get("segPromptPayloadSchemaOk", 0)) == 1
