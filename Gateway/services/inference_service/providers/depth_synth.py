from __future__ import annotations

import os

from PIL import Image

from services.inference_service.providers.depth_base import DepthMap


class SynthDepthProvider:
    """Deterministic synthetic depth provider for CI/tests."""

    name = "synth"

    def __init__(self) -> None:
        override = str(os.getenv("BYES_SERVICE_DEPTH_MODEL_ID", "")).strip()
        self.model = override or "depth-synth-v1"
        self.width = max(16, int(os.getenv("BYES_SYNTH_DEPTH_WIDTH", "64") or "64"))
        self.height = max(16, int(os.getenv("BYES_SYNTH_DEPTH_HEIGHT", "64") or "64"))

    def infer_depth(self, image: Image.Image, frame_seq: int | None = None) -> DepthMap:
        del image
        seq = int(frame_seq or 0)
        grid = [[2.5 for _ in range(self.width)] for _ in range(self.height)]

        if seq == 2:
            # Dropoff-like pattern: "far" region significantly deeper than "near".
            start_y = int(self.height * 0.65)
            split = start_y + max(1, (self.height - start_y) // 2)
            for y in range(start_y, split):
                for x in range(int(self.width * 0.3), int(self.width * 0.7)):
                    grid[y][x] = 3.3
            for y in range(split, self.height):
                for x in range(int(self.width * 0.3), int(self.width * 0.7)):
                    grid[y][x] = 0.9
        elif seq == 3:
            # Obstacle-close pattern: bottom-center includes very near depth.
            start_y = int(self.height * 0.65)
            for y in range(start_y, self.height):
                for x in range(int(self.width * 0.4), int(self.width * 0.6)):
                    grid[y][x] = 0.48

        values = [v for row in grid for v in row]
        return {
            "depth": grid,
            "min": min(values) if values else 0.0,
            "max": max(values) if values else 0.0,
            "scale": "relative",
            "width": self.width,
            "height": self.height,
            "model": self.model,
        }
