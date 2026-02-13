from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
from pydantic import ValidationError

from byes.config import GatewayConfig
from byes.schema import CoordFrame, DepthResult, ToolResult, ToolStatus
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane


class RealDepthTool(BaseTool):
    """External depth hazard tool (SLOW lane) with bounded inflight behavior."""

    name = "real_depth"
    version = "0.1.0"
    lane = ToolLane.SLOW
    capability = "depth"
    degradable = True

    def __init__(self, config: GatewayConfig) -> None:
        self.timeout_ms = max(50, int(config.real_depth_timeout_ms))
        self.p95_budget_ms = max(20, int(config.real_depth_p95_budget_ms))
        self._endpoint = str(config.real_depth_endpoint)
        self._max_inflight = max(1, int(config.real_depth_max_inflight))
        policy = str(config.real_depth_queue_policy).strip().lower()
        self._queue_policy = policy if policy in {"drop", "wait"} else "drop"
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

            timeout_s = max(0.05, self.timeout_ms / 1000.0)
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(
                    self._endpoint,
                    files={"image": ("frame.jpg", frame.frame_bytes, "image/jpeg")},
                    data={"meta": json.dumps(frame.meta, ensure_ascii=False)},
                )
                response.raise_for_status()
                payload = response.json()

            depth_result = _parse_depth_result(payload)
            hazards_payload = [hazard.model_dump(mode="json") for hazard in depth_result.hazards]
            confidence = max((float(item.confidence) for item in depth_result.hazards), default=0.0)
            summary = _summary_from_hazards(depth_result)
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
                    "hazards": hazards_payload,
                    "model": depth_result.model,
                    "latencyMs": depth_result.latencyMs,
                    "summary": summary,
                    "task": "depth",
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


def _parse_depth_result(payload: Any) -> DepthResult:
    if not isinstance(payload, dict):
        return DepthResult()
    try:
        return DepthResult.model_validate(payload)
    except ValidationError:
        # Keep gateway alive on partial schema mismatch from external service.
        hazards = payload.get("hazards")
        if not isinstance(hazards, list):
            hazards = []
        return DepthResult(hazards=[], model=str(payload.get("model", "")) or None, latencyMs=None)


def _summary_from_hazards(result: DepthResult) -> str:
    if not result.hazards:
        return "No nearby depth hazard"
    nearest = min(result.hazards, key=lambda item: float(item.distanceM))
    return (
        f"Depth hazard: {nearest.kind} at {nearest.distanceM:.2f}m, "
        f"azimuth {nearest.azimuthDeg:.1f}deg"
    )
