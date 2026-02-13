from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from byes.config import GatewayConfig
from byes.schema import CoordFrame, ToolResult, ToolStatus
from byes.tools.base import BaseTool, FrameInput, ToolContext, ToolLane


class RealVlmTool(BaseTool):
    """On-demand VLM tool (SLOW lane) enabled only when BYES_REAL_VLM_URL is configured."""

    name = "real_vlm"
    version = "0.1.0"
    lane = ToolLane.SLOW
    capability = "vlm"
    degradable = True

    def __init__(self, config: GatewayConfig) -> None:
        self.timeout_ms = max(100, int(config.real_vlm_timeout_ms))
        self.p95_budget_ms = max(80, min(self.timeout_ms, int(config.slow_budget_ms)))
        self._endpoint = str(config.real_vlm_url).strip()
        self._max_inflight = max(1, int(config.real_vlm_max_inflight))
        policy = str(config.real_vlm_queue_policy).strip().lower()
        self._queue_policy = policy if policy in {"drop_oldest", "drop_newest", "wait"} else "drop_newest"
        self._semaphore = asyncio.Semaphore(self._max_inflight)

    def should_skip(self, frame: FrameInput) -> str | None:
        intent = str(frame.meta.get("intent", "none")).strip().lower()
        if intent not in {"ask", "qa"}:
            return "policy"
        if self._queue_policy in {"drop_oldest", "drop_newest"} and self._semaphore.locked():
            return "queue_drop"
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
                    reason = "queue_drop"
                    return ToolResult(
                        toolName=self.name,
                        toolVersion=self.version,
                        seq=frame.seq,
                        tsCaptureMs=frame.ts_capture_ms,
                        latencyMs=0,
                        confidence=0.0,
                        coordFrame=CoordFrame.WORLD,
                        status=ToolStatus.CANCELLED,
                        error=f"skipped:{reason}",
                        payload={"reason": reason},
                    )

            payload = self._build_request_payload(frame)
            timeout_s = max(0.1, self.timeout_ms / 1000.0)
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(self._endpoint, json=payload)
                response.raise_for_status()
                body = response.json()
            if not isinstance(body, dict):
                raise ValueError("real_vlm response must be a JSON object")

            action_plan = body.get("actionPlan")
            if not isinstance(action_plan, dict):
                action_plan = {}

            answer_text = str(body.get("answerText", "")).strip()
            confidence = _clamp01(action_plan.get("confidence", body.get("confidence", 0.0)))
            latency_ms = int((time.perf_counter() - started) * 1000)
            result_payload: dict[str, Any] = {
                "answerText": answer_text,
                "actionPlan": action_plan,
                "summary": answer_text or str(action_plan.get("speech", "VLM response")),
                "diagnostics": body.get("diagnostics"),
                "task": "vlm",
            }
            return ToolResult(
                toolName=self.name,
                toolVersion=self.version,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                latencyMs=latency_ms,
                confidence=confidence,
                coordFrame=CoordFrame.WORLD,
                status=ToolStatus.OK,
                payload=result_payload,
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

    @staticmethod
    def _build_request_payload(frame: FrameInput) -> dict[str, Any]:
        meta = frame.meta if isinstance(frame.meta, dict) else {}
        frame_meta = meta.get("frameMeta")
        if not isinstance(frame_meta, dict):
            frame_meta = None
        question = str(meta.get("intentQuestion", "")).strip()
        if not question:
            question = str(meta.get("question", "")).strip()
        return {
            "sessionId": str(meta.get("sessionId", "default")),
            "question": question,
            "seq": frame.seq,
            "tsCaptureMs": frame.ts_capture_ms,
            "ttlMs": frame.ttl_ms,
            "frameMeta": frame_meta,
            "coordFrame": str(meta.get("coordFrame", "World")),
        }


def _clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
