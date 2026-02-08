from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from byes.config import GatewayConfig
from byes.schema import CoordFrame, ToolResult, ToolStatus
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane
from byes.tools.runner import HttpToolRunner, MultiModelRequest


class RealDetTool(BaseTool):
    """Real detector tool wrapper with runtime guards for latency and availability."""

    name = "real_det"
    version = "0.1.0"
    lane = ToolLane.SLOW
    capability = "det"
    degradable = True

    def __init__(self, config: GatewayConfig) -> None:
        self.timeout_ms = max(50, int(config.real_det_timeout_ms))
        self.p95_budget_ms = max(20, int(config.real_det_p95_budget_ms))
        self._max_inflight = max(1, int(config.real_det_max_inflight))
        policy = str(config.real_det_queue_policy).strip().lower()
        self._queue_policy = policy if policy in {"drop", "wait"} else "drop"
        self._runner = HttpToolRunner(config.real_det_endpoint)
        self._semaphore = asyncio.Semaphore(self._max_inflight)

    def should_skip(self, frame: FrameInput) -> str | None:
        _ = frame
        if self._queue_policy == "drop" and self._semaphore.locked():
            return "max_inflight"
        return None

    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        _ = ctx
        acquired = False
        started = time.perf_counter()
        try:
            if self._queue_policy == "wait":
                await self._semaphore.acquire()
                acquired = True
            else:
                acquired = await self._try_acquire_non_blocking()
                if not acquired:
                    return ToolResult(
                        toolName=self.name,
                        toolVersion=self.version,
                        seq=frame.seq,
                        tsCaptureMs=frame.ts_capture_ms,
                        latencyMs=0,
                        confidence=0.0,
                        coordFrame=CoordFrame.WORLD,
                        status=ToolStatus.CANCELLED,
                        error="skipped:max_inflight",
                        payload={"reason": "max_inflight", "queuePolicy": self._queue_policy},
                    )

            response = await self._runner.infer_bundle(
                MultiModelRequest(
                    frame_bytes=frame.frame_bytes,
                    roi=_extract_roi(frame.meta),
                    tasks=["det"],
                ),
                timeout_ms=self.timeout_ms,
            )
            detections = _normalize_detections(response.get("detections"))
            confidence = max((float(item.get("confidence", 0.0)) for item in detections), default=0.0)
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                toolName=self.name,
                toolVersion=self.version,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                latencyMs=latency_ms,
                confidence=confidence,
                coordFrame=CoordFrame.WORLD,
                status=ToolStatus.OK,
                payload={
                    "detections": detections,
                    "summary": _summary_from_detections(detections),
                    "task": "det",
                },
            )
        except httpx.TimeoutException as exc:
            raise asyncio.TimeoutError() from exc
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                toolName=self.name,
                toolVersion=self.version,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                latencyMs=latency_ms,
                confidence=0.0,
                coordFrame=CoordFrame.WORLD,
                status=ToolStatus.ERROR,
                error=str(exc),
                payload={},
            )
        finally:
            if acquired:
                self._semaphore.release()

    async def _try_acquire_non_blocking(self) -> bool:
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=0.001)
            return True
        except asyncio.TimeoutError:
            return False


def _extract_roi(meta: dict[str, Any]) -> dict[str, Any] | None:
    roi = meta.get("roi")
    if isinstance(roi, dict):
        return roi
    return None


def _normalize_detections(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cls = item.get("class")
        bbox = item.get("bbox")
        conf = item.get("confidence")
        normalized.append(
            {
                "class": str(cls) if cls is not None else "unknown",
                "bbox": bbox if isinstance(bbox, list) else [],
                "confidence": _clamp01(conf),
            }
        )
    return normalized


def _summary_from_detections(detections: list[dict[str, Any]]) -> str:
    if not detections:
        return "No object detected"
    top = max(detections, key=lambda item: float(item.get("confidence", 0.0)))
    cls = str(top.get("class", "object"))
    conf = _clamp01(top.get("confidence"))
    return f"Detected {cls} ({conf:.2f})"


def _clamp01(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
