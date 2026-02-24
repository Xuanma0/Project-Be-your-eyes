from __future__ import annotations

from typing import Any

from PIL import Image


class MockSegProvider:
    name = "mock"

    def __init__(self, model_id: str | None = None) -> None:
        self.model = str(model_id or "").strip() or "mock-seg"
        self.endpoint: str | None = None

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
        tracking: bool | None = None,
    ) -> dict[str, Any]:
        del image, frame_seq, run_id
        targets_used = [str(item).strip() for item in (targets or []) if str(item).strip()]
        del prompt
        return {
            "segments": [],
            "model": self.model,
            "targetsCount": len(targets_used),
            "targetsUsed": targets_used,
            "trackingUsed": bool(tracking),
        }
