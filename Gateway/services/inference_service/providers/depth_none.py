from __future__ import annotations

import os

from PIL import Image

from services.inference_service.providers.depth_base import DepthMap


class NoneDepthProvider:
    name = "none"

    def __init__(self) -> None:
        self.model = str(os.getenv("BYES_SERVICE_DEPTH_MODEL_ID", "none")).strip() or "none"

    def infer_depth(self, image: Image.Image, frame_seq: int | None = None) -> DepthMap | None:
        del image, frame_seq
        return None
