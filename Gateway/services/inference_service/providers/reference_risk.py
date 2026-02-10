from __future__ import annotations

import os
from typing import Any

from PIL import Image


class ReferenceRiskProvider:
    name = "reference"

    def __init__(self) -> None:
        default_model = str(os.getenv("BYES_REF_RISK_MODEL_ID", "reference-risk-v1")).strip() or "reference-risk-v1"
        override = str(os.getenv("BYES_SERVICE_RISK_MODEL_ID", "")).strip()
        self.model = override or default_model

    def infer(self, image: Image.Image, frame_seq: int | None) -> dict[str, Any]:
        del image
        if isinstance(frame_seq, int) and frame_seq % 3 == 0:
            hazards: list[dict[str, Any]] = [{"hazardKind": "dropoff", "severity": "critical", "score": 0.91}]
        else:
            hazards = [{"hazardKind": "stair_down", "severity": "warning", "score": 0.72}]
        return {"hazards": hazards, "model": self.model}
