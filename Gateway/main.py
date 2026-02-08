from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from byes.config import GatewayConfig, load_config
from byes.degradation import DegradationManager, DegradationState
from byes.faults import FaultManager
from byes.frame_tracker import FrameTracker
from byes.fusion import FusionEngine
from byes.metrics import GatewayMetrics
from byes.observability import Observability
from byes.planner import PolicyPlannerV0
from byes.safety import SafetyKernel
from byes.scheduler import Scheduler
from byes.schema import CoordFrame, EventEnvelope, EventType
from byes.tool_registry import ToolRegistry
from byes.tools import MockOcrTool, MockRiskTool, RealDetTool
from byes.tools.base import FrameInput, ToolLane


def _now_ms() -> int:
    return int(time.time() * 1000)


class MockEvent(BaseModel):
    type: str
    timestampMs: int
    coordFrame: str
    confidence: float
    ttlMs: int
    source: str
    riskText: str | None = None
    summary: str | None = None
    distanceM: float | None = None
    azimuthDeg: float | None = None


class FaultSetRequest(BaseModel):
    tool: Literal["mock_risk", "mock_ocr", "all"]
    mode: Literal["timeout", "slow", "low_conf", "disconnect"]
    value: float | bool | int | None = None
    durationMs: int | None = None


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.active.discard(ws)

    async def broadcast_json(self, obj: dict[str, Any]) -> None:
        failed: list[WebSocket] = []
        async with self._lock:
            targets = list(self.active)

        for ws in targets:
            try:
                await ws.send_json(obj)
            except Exception:  # noqa: BLE001
                failed.append(ws)

        if failed:
            async with self._lock:
                for ws in failed:
                    self.active.discard(ws)

    async def count(self) -> int:
        async with self._lock:
            return len(self.active)


class GatewayApp:
    SAFE_MODE_HEALTH_SUMMARY = (
        "System unstable. Safe mode active: risk alerts only. Please stop and scan surroundings."
    )

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.config: GatewayConfig = load_config()
        self.metrics = GatewayMetrics()
        self.observability = Observability("be-your-eyes-gateway")
        self.registry = ToolRegistry()
        self.degradation = DegradationManager(self.config, self.metrics)
        self.faults = FaultManager(self.metrics)
        self.frame_tracker = FrameTracker(
            metrics=self.metrics,
            retention_ms=self.config.frame_tracker_retention_ms,
            max_entries=self.config.frame_tracker_max_entries,
        )
        self.fusion = FusionEngine(self.config)
        self.planner = PolicyPlannerV0(self.config)
        self.safety = SafetyKernel(self.config, self.degradation)
        self.connections = ConnectionManager()
        self.scheduler = Scheduler(
            config=self.config,
            registry=self.registry,
            on_lane_results=self._on_lane_results,
            metrics=self.metrics,
            degradation_manager=self.degradation,
            observability=self.observability,
            fault_manager=self.faults,
            on_frame_terminal=self._on_frame_terminal,
            planner=self.planner,
        )
        self._mock_flip = False
        self._degrade_watchdog_task: asyncio.Task[None] | None = None
        self._last_safe_mode_pulse_ms = -1
        self._safe_mode_pulse_interval_ms = 1000

    async def startup(self) -> None:
        self.registry.register(MockRiskTool(self.config))
        self.registry.register(MockOcrTool(self.config))
        if self.config.enable_real_det:
            self.registry.register(RealDetTool(self.config))
        self.observability.instrument_app(self.app)
        await self.scheduler.start()
        self.degradation.set_ws_client_count(0)
        self._degrade_watchdog_task = asyncio.create_task(self._degradation_watchdog_loop())

    async def shutdown(self) -> None:
        if self._degrade_watchdog_task is not None:
            self._degrade_watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._degrade_watchdog_task
            self._degrade_watchdog_task = None

        await self.scheduler.stop()
        await self.faults.shutdown()

    async def submit_frame(self, frame_bytes: bytes, meta: dict[str, Any], request: Request) -> int:
        request_start_ms = _now_ms()
        trace = self.observability.extract_trace(request.headers)
        enriched_meta = dict(meta)
        enriched_meta["traceId"] = trace.trace_id
        enriched_meta["spanId"] = trace.span_id

        seq = await self.scheduler.submit_frame(
            frame_bytes=frame_bytes,
            meta=enriched_meta,
            trace_id=trace.trace_id,
            span_id=trace.span_id,
        )
        ttl_ms = int(enriched_meta.get("ttlMs", self.config.default_ttl_ms))
        if ttl_ms <= 0:
            ttl_ms = self.config.default_ttl_ms
        self.frame_tracker.start_frame(seq, request_start_ms, ttl_ms)
        return seq

    async def reset_runtime(self) -> dict[str, Any]:
        faults_snapshot = await self.faults.clear_faults()
        self.degradation.reset_runtime()
        self.frame_tracker.reset_runtime()
        self._last_safe_mode_pulse_ms = -1
        client_count = await self.connections.count()
        self.degradation.set_ws_client_count(client_count)
        return {
            "state": self.degradation.state.value,
            "clients": client_count,
            "hadClientEverConnected": self.degradation.had_client_ever_connected,
            "frameTrackerRecords": self.frame_tracker.record_count,
            "faults": faults_snapshot.get("faults", []),
        }

    def _on_frame_terminal(self, frame: FrameInput, outcome: str) -> None:
        self.frame_tracker.complete_frame(frame.seq, outcome, _now_ms())

    async def emit_degradation_changes(
        self,
        seq: int,
        ts_capture_ms: int,
        ttl_ms: int,
        trace_id: str,
        span_id: str,
    ) -> None:
        for change in self.degradation.consume_state_changes():
            if change.current == DegradationState.SAFE_MODE:
                status = "gateway_safe_mode"
            elif change.current == DegradationState.DEGRADED:
                status = "gateway_degraded"
            else:
                status = "gateway_normal"

            payload = {
                "status": status,
                "reason": change.reason,
                "summary": f"{status} ({change.reason})",
                "level": "info",
            }
            await self._emit_event(
                EventEnvelope(
                    type=EventType.HEALTH,
                    traceId=trace_id,
                    spanId=span_id,
                    seq=seq,
                    tsCaptureMs=ts_capture_ms,
                    ttlMs=ttl_ms,
                    coordFrame=CoordFrame.WORLD,
                    confidence=1.0,
                    priority=self.config.health_priority,
                    source="degradation@v1.1",
                    payload=payload,
                )
            )

        for alert in self.degradation.consume_alerts():
            payload = {
                "status": alert.status,
                "reason": alert.reason,
                "summary": f"{alert.status} ({alert.reason})",
                "level": "warn",
            }
            await self._emit_event(
                EventEnvelope(
                    type=EventType.HEALTH,
                    traceId=trace_id,
                    spanId=span_id,
                    seq=seq,
                    tsCaptureMs=ts_capture_ms,
                    ttlMs=ttl_ms,
                    coordFrame=CoordFrame.WORLD,
                    confidence=1.0,
                    priority=self.config.health_priority,
                    source="degradation@v1.1",
                    payload=payload,
                )
            )

    async def _degradation_watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            now_ms = _now_ms()
            self.degradation.tick()
            await self.emit_degradation_changes(
                seq=0,
                ts_capture_ms=now_ms,
                ttl_ms=self.config.default_ttl_ms,
                trace_id="0" * 32,
                span_id="0" * 16,
            )
            if self.degradation.is_safe_mode():
                if (
                    self._last_safe_mode_pulse_ms < 0
                    or now_ms - self._last_safe_mode_pulse_ms >= self._safe_mode_pulse_interval_ms
                ):
                    await self._emit_event(
                        EventEnvelope(
                            type=EventType.HEALTH,
                            traceId="0" * 32,
                            spanId="0" * 16,
                            seq=0,
                            tsCaptureMs=now_ms,
                            ttlMs=self.config.default_ttl_ms,
                            coordFrame=CoordFrame.WORLD,
                            confidence=1.0,
                            priority=self.config.health_priority,
                            source="degradation@v1.2.1",
                            payload={
                                "status": "gateway_safe_mode",
                                "summary": self.SAFE_MODE_HEALTH_SUMMARY,
                                "reason": "safe_mode_pulse",
                            },
                        )
                    )
                    self._last_safe_mode_pulse_ms = now_ms
            else:
                self._last_safe_mode_pulse_ms = -1

    async def _on_lane_results(self, frame: FrameInput, lane: ToolLane, results: list[Any]) -> None:
        trace_id = str(frame.meta.get("traceId", "0" * 32))
        span_id = str(frame.meta.get("spanId", "0" * 16))
        fused = self.fusion.fuse_lane(frame=frame, lane=lane, results=results, trace_id=trace_id, span_id=span_id)

        now = _now_ms()
        decision = self.safety.adjudicate(fused.events, now_ms=now)
        emitted_count = 0
        for event in decision.events:
            if event.is_expired(now):
                self.metrics.inc_deadline_miss(lane.value)
                continue
            await self._emit_event(event)
            emitted_count += 1

        if emitted_count > 0:
            self.frame_tracker.complete_frame(frame.seq, "ok", now)
        elif lane == ToolLane.FAST:
            # No final event from fast lane. In safe mode this is expected suppression.
            outcome = "safemode_suppressed" if self.degradation.is_safe_mode() else "error"
            self.frame_tracker.complete_frame(frame.seq, outcome, now)

        await self.emit_degradation_changes(
            seq=frame.seq,
            ts_capture_ms=frame.ts_capture_ms,
            ttl_ms=frame.ttl_ms,
            trace_id=trace_id,
            span_id=span_id,
        )

    async def _emit_event(self, event: EventEnvelope) -> None:
        if self.degradation.is_safe_mode() and event.type in {EventType.PERCEPTION, EventType.ACTION_PLAN}:
            tool_name = str(event.source).split("@", 1)[0] if event.source else "unknown"
            self.metrics.inc_tool_skipped(tool_name, "safe_mode")
            return
        if self.config.send_envelope:
            await self.connections.broadcast_json(event.model_dump(mode="json"))
            return
        await self.connections.broadcast_json(self.fusion.to_legacy_event(event))

    def build_mock_event(self) -> MockEvent:
        self._mock_flip = not self._mock_flip
        now_ms = _now_ms()
        if self._mock_flip:
            return MockEvent(
                type="risk",
                timestampMs=now_ms,
                coordFrame="World",
                confidence=0.9,
                ttlMs=3000,
                source="gateway",
                riskText="Obstacle ahead",
                distanceM=1.5,
                azimuthDeg=0.0,
            )
        return MockEvent(
            type="perception",
            timestampMs=now_ms,
            coordFrame="World",
            confidence=0.9,
            ttlMs=3000,
            source="gateway",
            summary="Door detected",
        )


app = FastAPI(title="BeYourEyes Gateway")
gateway = GatewayApp(app)


@app.on_event("startup")
async def _startup() -> None:
    await gateway.startup()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await gateway.shutdown()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "ts": _now_ms(),
        "state": gateway.degradation.state.value,
        "clients": len(gateway.connections.active),
        "hadClientEverConnected": gateway.degradation.had_client_ever_connected,
        "faults": gateway.faults.snapshot().get("faults", []),
    }


@app.get("/api/mock_event", response_model=MockEvent)
def mock_event() -> MockEvent:
    return gateway.build_mock_event()


@app.get("/api/tools")
def list_tools() -> dict[str, Any]:
    return {"tools": [item.__dict__ for item in gateway.registry.list_descriptors()]}


@app.post("/api/frame")
async def frame(
    request: Request,
    image: UploadFile = File(...),
    meta: str | None = Form(None),
) -> dict[str, Any]:
    frame_bytes = await image.read()
    meta_json: dict[str, Any] = {}
    if meta:
        with contextlib.suppress(json.JSONDecodeError):
            meta_json = json.loads(meta)

    seq = await gateway.submit_frame(frame_bytes=frame_bytes, meta=meta_json, request=request)
    return {"ok": True, "bytes": len(frame_bytes), "seq": seq}


@app.post("/api/fault/set")
async def fault_set(request: FaultSetRequest) -> dict[str, Any]:
    try:
        snapshot = await gateway.faults.set_fault(
            tool=request.tool,
            mode=request.mode,
            value=request.value,
            duration_ms=request.durationMs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **snapshot}


@app.post("/api/fault/clear")
async def fault_clear() -> dict[str, Any]:
    snapshot = await gateway.faults.clear_faults()
    return {"ok": True, **snapshot}


@app.post("/api/dev/reset")
async def dev_reset() -> dict[str, Any]:
    runtime = await gateway.reset_runtime()
    return {"ok": True, **runtime}


@app.get("/metrics")
def metrics() -> Response:
    rendered = gateway.metrics.render()
    return Response(content=rendered.content, media_type=rendered.content_type)


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await gateway.connections.connect(websocket)
    gateway.degradation.set_ws_client_count(await gateway.connections.count())
    await gateway.emit_degradation_changes(
        seq=0,
        ts_capture_ms=_now_ms(),
        ttl_ms=gateway.config.default_ttl_ms,
        trace_id="0" * 32,
        span_id="0" * 16,
    )

    try:
        while True:
            message = await websocket.receive_text()
            if message == "__ping__":
                await websocket.send_text("__pong__")
    except WebSocketDisconnect:
        pass
    finally:
        await gateway.connections.disconnect(websocket)
        gateway.degradation.set_ws_client_count(await gateway.connections.count())
        await gateway.emit_degradation_changes(
            seq=0,
            ts_capture_ms=_now_ms(),
            ttl_ms=gateway.config.default_ttl_ms,
            trace_id="0" * 32,
            span_id="0" * 16,
        )
