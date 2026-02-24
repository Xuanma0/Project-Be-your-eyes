from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from services.reference_seg_service import app as ref_app


def test_reference_seg_service_prompt_filtering_and_fallback(tmp_path: Path, monkeypatch) -> None:
    fixture_src = Path(__file__).resolve().parent / "fixtures" / "run_package_with_seg_prompt_and_mask_gt_min"
    fixture_dir = tmp_path / "seg_prompt_mask_fixture"
    shutil.copytree(fixture_src, fixture_dir)

    monkeypatch.setenv("BYES_REF_SEG_FIXTURE_DIR", str(fixture_dir))
    monkeypatch.setenv("BYES_REF_SEG_RUN_ID", "fixture-seg-prompt-mask")

    previous_state = getattr(ref_app.app.state, "seg_state", None)
    ref_app.app.state.seg_state = ref_app._load_state()
    try:
        with TestClient(ref_app.app) as client:
            filtered_resp = client.post(
                "/seg",
                json={
                    "runId": "fixture-seg-prompt-mask",
                    "frameSeq": 1,
                    "image_b64": "",
                    "prompt": {"targets": ["person"], "text": "find person", "meta": {"promptVersion": "v1"}},
                },
            )
            assert filtered_resp.status_code == 200, filtered_resp.text
            filtered_body = filtered_resp.json()
            filtered_segments = filtered_body.get("segments", [])
            assert len(filtered_segments) == 1
            assert str(filtered_segments[0].get("label", "")).lower() == "person"
            assert isinstance(filtered_segments[0].get("mask"), dict)

            fallback_resp = client.post(
                "/seg",
                json={
                    "runId": "fixture-seg-prompt-mask",
                    "frameSeq": 1,
                    "image_b64": "",
                    "prompt": {"boxes": [[99, 99, 120, 120]]},
                },
            )
            assert fallback_resp.status_code == 200, fallback_resp.text
            fallback_body = fallback_resp.json()
            fallback_segments = fallback_body.get("segments", [])
            assert len(fallback_segments) == 2
            assert str(fallback_body.get("promptWarning", "")).startswith("prompt_filter_empty_fallback")
    finally:
        if previous_state is None:
            delattr(ref_app.app.state, "seg_state")
        else:
            ref_app.app.state.seg_state = previous_state
