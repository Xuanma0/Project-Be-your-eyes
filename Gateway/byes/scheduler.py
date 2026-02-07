from __future__ import annotations

import asyncio
import contextlib
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from byes.config import GatewayConfig
from byes.observability import Observability, TraceInfo
from byes.schema import ToolResult, ToolStatus
from byes.tool_registry import ToolRegistry
from byes.tools.base import FrameInput, ToolContext, ToolLane

OnLaneResults = Callable[[FrameInput, ToolLane, list[ToolResult]], Awaitable[None]]


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class _QueuedTask:
    frame: FrameInput
    trace_id: str
    span_id: str


class Scheduler:
    def __init__(
        self,
        config: GatewayConfig,
        registry: ToolRegistry,
        on_lane_results: OnLaneResults,
        metrics: Any | None = None,
        degradation_manager: Any | None = None,
        observability: Observability | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._on_lane_results = on_lane_results
        self._metrics = metrics
        self._degradation = degradation_manager
        self._observability = observability

        self._seq = 0
        self._latest_seq = 0
        self._lock = asyncio.Lock()
        self._running = False

        self._fast_q: asyncio.Queue[_QueuedTask] = asyncio.Queue(maxsize=config.fast_q_maxsize)
        self._slow_q: asyncio.Queue[_QueuedTask] = asyncio.Queue(maxsize=config.slow_q_maxsize)
        self._workers: list[asyncio.Task[None]] = []
        self._active_by_seq: dict[int, set[asyncio.Task[ToolResult]]] = defaultdict(set)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker_loop(ToolLane.FAST), name="byes-fast-worker"),
            asyncio.create_task(self._worker_loop(ToolLane.SLOW), name="byes-slow-worker"),
        ]
        self._set_queue_depth_metrics()

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        for worker in self._workers:
            worker.cancel()

        for tasks in self._active_by_seq.values():
            for task in tasks:
                task.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._active_by_seq.clear()
        self._set_queue_depth_metrics()

    async def submit_frame(
        self,
        frame_bytes: bytes,
        meta: dict[str, Any] | None,
        trace_id: str,
        span_id: str,
    ) -> int:
        if not self._running:
            raise RuntimeError("scheduler is not running")

        payload = dict(meta or {})
        now = _now_ms()
        ts_capture_ms = int(payload.get("tsCaptureMs", now))
        ttl_ms = int(payload.get("ttlMs", self._config.default_ttl_ms))
        ttl_ms = ttl_ms if ttl_ms > 0 else self._config.default_ttl_ms
        preserve_old = bool(payload.get("preserveOld", False))

        async with self._lock:
            self._seq += 1
            seq = self._seq
            self._latest_seq = max(self._latest_seq, seq)
            if not preserve_old:
                self._cancel_older_active(seq)

        frame = FrameInput(
            seq=seq,
            ts_capture_ms=ts_capture_ms,
            ttl_ms=ttl_ms,
            frame_bytes=frame_bytes,
            meta=payload,
        )
        queued = _QueuedTask(frame=frame, trace_id=trace_id, span_id=span_id)

        # FAST queue should not drop. It can back up but remains lossless for risk lane.
        await self._fast_q.put(queued)
        self._set_queue_depth_metrics()

        # SLOW queue applies backpressure dropping low-priority work.
        if self._slow_q.qsize() >= self._config.slow_q_drop_threshold:
            self._metric_call("inc_backpressure_drop", ToolLane.SLOW.value)
            self._safe_call(self._degradation, "note_backpressure", ToolLane.SLOW.value)
        else:
            with contextlib.suppress(asyncio.QueueFull):
                self._slow_q.put_nowait(queued)
        self._set_queue_depth_metrics()

        return seq

    async def _worker_loop(self, lane: ToolLane) -> None:
        queue = self._fast_q if lane == ToolLane.FAST else self._slow_q
        while True:
            queued = await queue.get()
            self._set_queue_depth_metrics()
            try:
                if self._should_skip_frame(queued.frame):
                    continue

                if self._is_expired(queued.frame.ts_capture_ms, queued.frame.ttl_ms, _now_ms()):
                    self._metric_call("inc_deadline_miss", lane.value)
                    continue

                results = await self._run_tools_for_lane(queued, lane)
                if results:
                    await self._on_lane_results(queued.frame, lane, results)
            finally:
                queue.task_done()
                self._set_queue_depth_metrics()

    async def _run_tools_for_lane(self, queued: _QueuedTask, lane: ToolLane) -> list[ToolResult]:
        tools = self._registry.lane_tools(
            lane=lane,
            degraded=bool(self._safe_call(self._degradation, "is_degraded", default=False)),
            safe_mode=bool(self._safe_call(self._degradation, "is_safe_mode", default=False)),
        )
        if not tools:
            return []

        tasks: list[asyncio.Task[ToolResult]] = []
        for tool in tools:
            task = asyncio.create_task(self._run_single_tool(tool, queued, lane))
            self._active_by_seq[queued.frame.seq].add(task)
            tasks.append(task)

        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[ToolResult] = []
        for item in gathered:
            if isinstance(item, ToolResult):
                results.append(item)
                self._safe_call(self._degradation, "record_tool_result", item)

        self._active_by_seq.pop(queued.frame.seq, None)
        return results

    async def _run_single_tool(self, tool: Any, queued: _QueuedTask, lane: ToolLane) -> ToolResult:
        frame = queued.frame
        now = _now_ms()
        lane_deadline = self._config.fast_lane_deadline_ms if lane == ToolLane.FAST else self._config.slow_lane_deadline_ms
        ttl_left_ms = frame.ts_capture_ms + frame.ttl_ms - now
        timeout_ms = min(int(getattr(tool, "timeout_ms", lane_deadline)), lane_deadline, ttl_left_ms)

        if timeout_ms <= 0:
            self._metric_call("inc_deadline_miss", lane.value)
            return ToolResult(
                toolName=tool.name,
                toolVersion=tool.version,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                latencyMs=0,
                confidence=0.0,
                status=ToolStatus.DROPPED_EXPIRED,
                payload={},
            )

        ctx = ToolContext(
            trace_id=queued.trace_id,
            span_id=queued.span_id,
            deadline_ms=now + timeout_ms,
            meta=frame.meta,
        )
        trace = TraceInfo(trace_id=queued.trace_id, span_id=queued.span_id, context=None)

        started = time.perf_counter()
        success_elapsed_ms = 0
        with self._tool_span(trace, tool, lane, frame, timeout_ms) as span:
            try:
                result = await asyncio.wait_for(tool.infer(frame, ctx), timeout=timeout_ms / 1000.0)
                success_elapsed_ms = int((time.perf_counter() - started) * 1000)
                result.latencyMs = max(result.latencyMs, success_elapsed_ms)
                if span is not None:
                    span.set_attribute("tool.timeout", False)
                    span.set_attribute("tool.status", result.status.value)
                    span.set_attribute("tool.latency_ms", result.latencyMs)
            except asyncio.TimeoutError:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._safe_call(self._degradation, "record_timeout", tool.name)
                self._metric_call("observe_tool_latency", tool.name, elapsed_ms)
                if span is not None:
                    span.set_attribute("tool.timeout", True)
                    span.set_attribute("tool.status", ToolStatus.TIMEOUT.value)
                    span.set_attribute("tool.latency_ms", elapsed_ms)
                return ToolResult(
                    toolName=tool.name,
                    toolVersion=tool.version,
                    seq=frame.seq,
                    tsCaptureMs=frame.ts_capture_ms,
                    latencyMs=elapsed_ms,
                    confidence=0.0,
                    status=ToolStatus.TIMEOUT,
                    error="timeout",
                    payload={},
                )
            except asyncio.CancelledError:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._metric_call("observe_tool_latency", tool.name, elapsed_ms)
                if span is not None:
                    span.set_attribute("tool.status", ToolStatus.CANCELLED.value)
                    span.set_attribute("tool.latency_ms", elapsed_ms)
                return ToolResult(
                    toolName=tool.name,
                    toolVersion=tool.version,
                    seq=frame.seq,
                    tsCaptureMs=frame.ts_capture_ms,
                    latencyMs=elapsed_ms,
                    confidence=0.0,
                    status=ToolStatus.CANCELLED,
                    error="cancelled",
                    payload={},
                )
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._metric_call("observe_tool_latency", tool.name, elapsed_ms)
                if span is not None:
                    span.set_attribute("tool.status", ToolStatus.ERROR.value)
                    span.set_attribute("tool.error", str(exc))
                    span.set_attribute("tool.latency_ms", elapsed_ms)
                return ToolResult(
                    toolName=tool.name,
                    toolVersion=tool.version,
                    seq=frame.seq,
                    tsCaptureMs=frame.ts_capture_ms,
                    latencyMs=elapsed_ms,
                    confidence=0.0,
                    status=ToolStatus.ERROR,
                    error=str(exc),
                    payload={},
                )

        if success_elapsed_ms <= 0:
            success_elapsed_ms = int((time.perf_counter() - started) * 1000)
            result.latencyMs = max(result.latencyMs, success_elapsed_ms)
        self._metric_call("observe_tool_latency", tool.name, result.latencyMs)

        if self._is_expired(frame.ts_capture_ms, frame.ttl_ms, _now_ms()):
            self._metric_call("inc_deadline_miss", lane.value)
            result.status = ToolStatus.DROPPED_EXPIRED
            result.payload = {}
            return result

        return result

    def _cancel_older_active(self, new_seq: int) -> None:
        for seq, tasks in list(self._active_by_seq.items()):
            if seq >= new_seq:
                continue
            for task in list(tasks):
                if not task.done():
                    task.cancel()

    def _should_skip_frame(self, frame: FrameInput) -> bool:
        if bool(frame.meta.get("preserveOld", False)):
            return False
        return frame.seq < self._latest_seq

    @staticmethod
    def _is_expired(ts_capture_ms: int, ttl_ms: int, now_ms: int) -> bool:
        return now_ms - ts_capture_ms > ttl_ms

    def _set_queue_depth_metrics(self) -> None:
        self._metric_call("set_queue_depth", ToolLane.FAST.value, self._fast_q.qsize())
        self._metric_call("set_queue_depth", ToolLane.SLOW.value, self._slow_q.qsize())

    def _tool_span(self, trace: TraceInfo, tool: Any, lane: ToolLane, frame: FrameInput, timeout_ms: int):
        if self._observability is None:
            return contextlib.nullcontext(None)
        return self._observability.start_span(
            "tool.infer",
            trace,
            tool_name=getattr(tool, "name", "tool"),
            tool_lane=lane.value,
            frame_seq=frame.seq,
            timeout_ms=timeout_ms,
        )

    def _metric_call(self, method: str, *args: Any) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)

    @staticmethod
    def _safe_call(target: Any | None, method: str, *args: Any, default: Any = None) -> Any:
        if target is None:
            return default
        fn = getattr(target, method, None)
        if not callable(fn):
            return default
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001
            return default
