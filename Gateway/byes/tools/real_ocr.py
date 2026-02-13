from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from byes.config import GatewayConfig
from byes.schema import CoordFrame, ToolResult, ToolStatus
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane


class RealOcrTool(BaseTool):
    """External OCR tool wrapper for scan_text intent flow."""

    name = "real_ocr"
    version = "0.1.0"
    lane = ToolLane.SLOW
    capability = "ocr"
    degradable = True

    def __init__(self, config: GatewayConfig) -> None:
        self.timeout_ms = max(50, int(config.real_ocr_timeout_ms))
        self.p95_budget_ms = max(20, int(config.real_ocr_p95_budget_ms))
        self._endpoint = str(config.real_ocr_endpoint)
        self._max_inflight = max(1, int(config.real_ocr_max_inflight))
        policy = str(config.real_ocr_queue_policy).strip().lower()
        self._queue_policy = policy if policy in {"drop", "wait"} else "drop"
        self._semaphore = asyncio.Semaphore(self._max_inflight)

    def should_skip(self, frame: FrameInput) -> str | None:
        if str(frame.meta.get("intent", "none")).lower() != "scan_text":
            return "policy"
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
                )
                response.raise_for_status()
                payload = response.json()

            if not isinstance(payload, dict):
                raise ValueError("ocr response must be a JSON object")

            lines_raw = payload.get("lines", [])
            lines = _normalize_lines(lines_raw)
            if lines:
                best_score = max(float(item.get("score", 0.0)) for item in lines)
            else:
                best_score = 0.0
            summary = str(payload.get("summary", "")).strip()
            if not summary:
                summary = _summary_from_lines(lines)
            text = summary
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                toolName=self.name,
                toolVersion=self.version,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                latencyMs=latency_ms,
                confidence=max(0.0, min(1.0, best_score)),
                coordFrame=CoordFrame.WORLD,
                status=ToolStatus.OK,
                payload={
                    "text": text,
                    "summary": summary,
                    "lines": lines,
                    "task": "ocr",
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


def _normalize_lines(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        score = _clamp01(item.get("score"))
        box = item.get("box")
        out.append(
            {
                "text": text,
                "score": score,
                "box": box if isinstance(box, list) else [],
            }
        )
    return out


def _summary_from_lines(lines: list[dict[str, Any]]) -> str:
    if not lines:
        return "No readable text detected"
    top = max(lines, key=lambda item: float(item.get("score", 0.0)))
    text = str(top.get("text", "")).strip()
    if not text:
        return "Text detected"
    return f"Text detected: {text}"


def _clamp01(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
