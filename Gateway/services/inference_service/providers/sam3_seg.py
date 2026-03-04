from __future__ import annotations

import os

from services.inference_service.providers.http_seg import HttpSegProvider


class Sam3SegProvider(HttpSegProvider):
    name = "sam3"

    def __init__(self) -> None:
        endpoint = str(
            os.getenv("BYES_SERVICE_SEG_ENDPOINT", os.getenv("BYES_SEG_HTTP_URL", "http://127.0.0.1:19120/seg"))
        ).strip()
        timeout_ms = int(str(os.getenv("BYES_SERVICE_SEG_TIMEOUT_MS", "1500")).strip() or "1500")
        model_id = str(os.getenv("BYES_SERVICE_SAM3_CKPT", os.getenv("BYES_SAM3_WEIGHTS", ""))).strip() or "sam3"
        super().__init__(
            endpoint=endpoint,
            model_id=model_id,
            timeout_ms=timeout_ms,
            downstream="sam3",
            tracking=True,
        )
