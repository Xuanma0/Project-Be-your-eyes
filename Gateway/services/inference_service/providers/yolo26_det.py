from __future__ import annotations

import os

from services.inference_service.providers.ultralytics_det import UltralyticsDetProvider


class Yolo26DetProvider(UltralyticsDetProvider):
    name = "yolo26"

    def __init__(self) -> None:
        yolo26_weights = str(os.getenv("BYES_YOLO26_WEIGHTS", "")).strip()
        if yolo26_weights and not str(os.getenv("BYES_SERVICE_DET_MODEL_PATH", "")).strip():
            os.environ["BYES_SERVICE_DET_MODEL_PATH"] = yolo26_weights
        if not str(os.getenv("BYES_SERVICE_DET_MODEL", "")).strip():
            os.environ["BYES_SERVICE_DET_MODEL"] = "yolo26"
        super().__init__()
        if self.model == "yolo26" and yolo26_weights:
            self.model = yolo26_weights
