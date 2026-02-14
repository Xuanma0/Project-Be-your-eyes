from __future__ import annotations

import base64
import io
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from services.inference_service import app as inference_app


class CaptureSegProvider:
    name = "mock"
    model = "capture-seg-v1"
    endpoint = None

    def __init__(self) -> None:
        self.last_prompt: dict[str, Any] | None = None
        self.last_targets: list[str] = []

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del image, frame_seq, run_id
        self.last_targets = [str(item).strip() for item in (targets or []) if str(item).strip()]
        self.last_prompt = dict(prompt) if isinstance(prompt, dict) else None
        return {
            "segments": [{"label": "person", "score": 0.9, "bbox": [0, 0, 10, 10]}],
            "model": self.model,
            "targetsCount": len(self.last_targets),
            "targetsUsed": self.last_targets,
        }


def _encode_image_b64() -> str:
    image = Image.new("RGB", (64, 64), (100, 120, 140))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_inference_service_seg_prompt_request_passthrough() -> None:
    provider = CaptureSegProvider()
    original = inference_app._SEG_PROVIDER  # type: ignore[attr-defined]
    inference_app._SEG_PROVIDER = provider  # type: ignore[attr-defined]
    try:
        with TestClient(inference_app.app) as client:
            payload = {
                "image_b64": _encode_image_b64(),
                "frameSeq": 1,
                "targets": ["person", "stairs"],
                "prompt": {
                    "schemaVersion": "byes.seg_request.v1",
                    "targets": ["person", "stairs"],
                    "text": "find stairs and handrail",
                    "boxes": [[0, 0, 32, 32]],
                    "points": [{"x": 8, "y": 8, "label": 1}],
                    "meta": {"promptVersion": "v1"},
                },
            }
            response = client.post("/seg", json=payload)
            assert response.status_code == 200, response.text
            body = response.json()

        assert isinstance(provider.last_prompt, dict)
        assert provider.last_prompt.get("text") == "find stairs and handrail"
        assert provider.last_prompt.get("meta", {}).get("promptVersion") == "v1"
        assert provider.last_targets == ["person", "stairs"]
        assert body.get("model") == "capture-seg-v1"
        assert isinstance(body.get("segments"), list)
    finally:
        inference_app._SEG_PROVIDER = original  # type: ignore[attr-defined]
