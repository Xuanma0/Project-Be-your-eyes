from __future__ import annotations

import time
from typing import Any

from byes.inference.backends.base import OCRResult, RiskResult, SegResult, DepthResult, SlamResult


def _now_ms() -> int:
    return int(time.time() * 1000)


class MockOCRBackend:
    name = "mock"

    def __init__(self, text: str = "EXIT", confidence: float = 0.9, model_id: str = "mock-ocr") -> None:
        self._text = str(text)
        self._confidence = float(confidence)
        self.model_id: str | None = str(model_id or "").strip() or "mock-ocr"
        self.endpoint: str | None = None

    async def infer(
        self,
        image_bytes: bytes,
        frame_seq: int | None,
        ts_ms: int,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> OCRResult:
        started = _now_ms()
        del image_bytes, frame_seq, ts_ms, run_id, targets, prompt
        latency = max(0, _now_ms() - started)
        lines = [{"text": self._text, "score": max(0.0, min(1.0, self._confidence))}]
        return OCRResult(
            text=self._text,
            lines=lines,
            latency_ms=latency,
            status="ok",
            payload={
                "schemaVersion": "byes.ocr.v1",
                "lines": lines,
                "linesCount": 1,
                "backend": "mock",
            },
        )


class MockRiskBackend:
    name = "mock"

    def __init__(self, hazards: list[dict[str, Any]] | None = None, model_id: str = "mock-risk") -> None:
        self._hazards = list(hazards) if hazards is not None else [
            {"hazardKind": "stair_down", "severity": "warning"},
        ]
        self.model_id: str | None = str(model_id or "").strip() or "mock-risk"
        self.endpoint: str | None = None

    async def infer(self, image_bytes: bytes, frame_seq: int | None, ts_ms: int) -> RiskResult:
        started = _now_ms()
        del image_bytes, frame_seq, ts_ms
        latency = max(0, _now_ms() - started)
        return RiskResult(
            hazards=list(self._hazards),
            latency_ms=latency,
            status="ok",
            payload={
                "hazards": list(self._hazards),
                "backend": "mock",
            },
        )


class MockSegBackend:
    name = "mock"

    def __init__(self, segments: list[dict[str, Any]] | None = None, model_id: str = "mock-seg") -> None:
        self._segments = list(segments) if segments is not None else []
        self.model_id: str | None = str(model_id or "").strip() or "mock-seg"
        self.endpoint: str | None = None

    async def infer(
        self,
        image_bytes: bytes,
        frame_seq: int | None,
        ts_ms: int,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> SegResult:
        started = _now_ms()
        del image_bytes, frame_seq, ts_ms, run_id
        latency = max(0, _now_ms() - started)
        normalized_targets = [str(item).strip() for item in (targets or []) if str(item).strip()]
        del prompt
        return SegResult(
            segments=list(self._segments),
            latency_ms=latency,
            status="ok",
            payload={
                "segments": list(self._segments),
                "segmentsCount": len(self._segments),
                "backend": "mock",
                "targetsCount": len(normalized_targets),
                "targetsUsed": normalized_targets,
            },
        )


class MockDepthBackend:
    name = "mock"

    def __init__(self, model_id: str = "mock-depth", grid_size: tuple[int, int] = (16, 16)) -> None:
        self.model_id: str | None = str(model_id or "").strip() or "mock-depth"
        self.endpoint: str | None = None
        self._grid_size = (max(1, int(grid_size[0])), max(1, int(grid_size[1])))

    async def infer(
        self,
        image_bytes: bytes,
        frame_seq: int | None,
        ts_ms: int,
        run_id: str | None = None,
        targets: list[str] | None = None,
    ) -> DepthResult:
        started = _now_ms()
        del image_bytes, ts_ms, run_id, targets
        gw, gh = self._grid_size
        seq = int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1
        base = 900 + (seq % 5) * 25
        values: list[int] = []
        for y in range(gh):
            for x in range(gw):
                values.append(int(max(0, min(65535, base + x * 6 + y * 4))))
        latency = max(0, _now_ms() - started)
        grid = {"format": "grid_u16_mm_v1", "size": [gw, gh], "unit": "mm", "values": values}
        return DepthResult(
            grid=grid,
            latency_ms=latency,
            status="ok",
            payload={
                "grid": grid,
                "gridCount": 1,
                "valuesCount": len(values),
                "backend": self.name,
            },
        )


class MockSlamBackend:
    name = "mock"

    def __init__(self, model_id: str = "mock-slam") -> None:
        self.model_id: str | None = str(model_id or "").strip() or "mock-slam"
        self.endpoint: str | None = None

    async def infer(
        self,
        image_bytes: bytes,
        frame_seq: int | None,
        ts_ms: int,
        run_id: str | None = None,
        targets: list[str] | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> SlamResult:
        started = _now_ms()
        del image_bytes, ts_ms, run_id, targets, prompt
        seq = int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1
        tracking_state = "tracking"
        if seq % 11 == 0:
            tracking_state = "relocalized"
        if seq % 13 == 0:
            tracking_state = "lost"
        tx = round(0.05 * float(seq - 1), 6)
        pose = {
            "t": [tx, 0.0, 0.0],
            "q": [0.0, 0.0, 0.0, 1.0],
            "frame": "world_to_cam",
            "mapId": "mock-map",
        }
        latency = max(0, _now_ms() - started)
        return SlamResult(
            tracking_state=tracking_state,
            pose=pose,
            latency_ms=latency,
            status="ok",
            payload={
                "schemaVersion": "byes.slam_pose.v1",
                "trackingState": tracking_state,
                "pose": pose,
                "backend": self.name,
                "warningsCount": 0,
            },
        )
