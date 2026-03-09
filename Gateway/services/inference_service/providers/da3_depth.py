from __future__ import annotations

import os

from services.inference_service.providers.http_depth import HttpDepthProvider


class Da3DepthProvider(HttpDepthProvider):
    name = "da3"

    def __init__(self) -> None:
        endpoint = str(
            os.getenv("BYES_SERVICE_DEPTH_ENDPOINT", os.getenv("BYES_DEPTH_HTTP_URL", "http://127.0.0.1:19120/depth"))
        ).strip()
        timeout_ms = int(str(os.getenv("BYES_SERVICE_DEPTH_TIMEOUT_MS", "1500")).strip() or "1500")
        model_id = (
            str(
                os.getenv(
                    "BYES_SERVICE_DEPTH_ONNX_PATH",
                    os.getenv("BYES_DA3_WEIGHTS", ""),
                )
            ).strip()
            or "da3"
        )
        ref_strategy = str(os.getenv("BYES_SERVICE_DEPTH_HTTP_REF_VIEW_STRATEGY", "")).strip() or None
        super().__init__(
            endpoint=endpoint,
            model_id=model_id,
            timeout_ms=timeout_ms,
            downstream="da3",
            ref_view_strategy=ref_strategy,
        )
