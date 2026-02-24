from __future__ import annotations

from typing import Any

from PIL import Image


class MockDepthProvider:
    name = "mock"

    def __init__(self, model_id: str | None = None, grid_size: tuple[int, int] = (16, 16)) -> None:
        self.model = str(model_id or "").strip() or "mock-depth"
        self.endpoint: str | None = None
        gw = max(1, int(grid_size[0]))
        gh = max(1, int(grid_size[1]))
        self._grid_size = (gw, gh)

    def infer(
        self,
        image: Image.Image,
        frame_seq: int | None,
        run_id: str | None = None,
        targets: list[str] | None = None,
        ref_view_strategy: str | None = None,
        pose: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del run_id, targets
        width, height = image.size
        gw, gh = self._grid_size
        seq = int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1
        base = 900 + (seq % 5) * 25
        values: list[int] = []
        for y in range(gh):
            for x in range(gw):
                values.append(int(max(0, min(65535, base + x * 6 + y * 4))))
        payload: dict[str, Any] = {
            "backend": self.name,
            "model": self.model,
            "endpoint": self.endpoint,
            "imageWidth": int(width),
            "imageHeight": int(height),
            "grid": {
                "format": "grid_u16_mm_v1",
                "size": [gw, gh],
                "unit": "mm",
                "values": values,
            },
            "valuesCount": len(values),
            "gridCount": 1,
        }
        meta: dict[str, Any] = {"provider": self.name}
        ref_text = str(ref_view_strategy or "").strip()
        if ref_text:
            meta["refViewStrategy"] = ref_text
        if pose is not None:
            meta["poseUsed"] = isinstance(pose, dict)
        if meta:
            payload["meta"] = meta
        return payload
