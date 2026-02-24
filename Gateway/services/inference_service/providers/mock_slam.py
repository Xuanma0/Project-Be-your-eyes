from __future__ import annotations

from typing import Any

from PIL import Image


class MockSlamProvider:
    name = "mock"

    def __init__(self, model_id: str | None = None) -> None:
        self.model = str(model_id or "").strip() or "mock-slam"
        self.endpoint: str | None = None

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del image, run_id, targets, prompt
        seq = int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1
        state = "tracking"
        if seq % 11 == 0:
            state = "relocalized"
        if seq % 13 == 0:
            state = "lost"
        tx = round(0.05 * float(seq - 1), 6)
        pose = {
            "t": [tx, 0.0, 0.0],
            "q": [0.0, 0.0, 0.0, 1.0],
            "frame": "world_to_cam",
            "mapId": "mock-map",
        }
        return {
            "schemaVersion": "byes.slam_pose.v1",
            "trackingState": state,
            "pose": pose,
            "backend": self.name,
            "model": self.model,
            "endpoint": self.endpoint,
        }
