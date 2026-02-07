from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any

from fastapi import FastAPI, File, Form, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from byes.config import GatewayConfig, load_config
from byes.degradation import DegradationManager, DegradationState
from byes.fusion import FusionEngine
from byes.metrics import GatewayMetrics
from byes.observability import Observability
from byes.safety import SafetyKernel
from byes.scheduler import Scheduler
from byes.schema import CoordFrame, EventEnvelope, EventType
from byes.tool_registry import ToolRegistry
from byes.tools import MockOcrTool, MockRiskTool
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

    async def broadcast_text(self, text: str) -> None:
        failed: list[WebSocket] = []
        async with self._lock:
            targets = list(self.active)

        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001
                failed.append(ws)

        if failed:
            async with self._lock:
                for ws in failed:
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
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.config: GatewayConfig = load_config()
        self.metrics = GatewayMetrics()
        self.observability = Observability("be-your-eyes-gateway")
        self.registry = ToolRegistry()
        self.degradation = DegradationManager(self.config, self.metrics)
        self.fusion = FusionEngine(self.config)
        self.safety = SafetyKernel(self.config, self.degradation)
        self.connections = ConnectionManager()
        self.scheduler = Scheduler(
            config=self.config,
            registry=self.registry,
            on_lane_results=self._on_lane_results,
            metrics=self.metrics,
            degradation_manager=self.degradation,
            observability=self.observability,
        )
        self._mock_flip = False

    async def startup(self) -> None:
        self.registry.register(MockRiskTool(self.config))
        self.registry.register(MockOcrTool(self.config))
        self.observability.instrument_app(self.app)
        await self.scheduler.start()
        self.degradation.set_ws_client_count(0)

    async def shutdown(self) -> None:
        await self.scheduler.stop()

    async def submit_frame(self, frame_bytes: bytes, meta: dict[str, Any], request: Request) -> int:
        trace = self.observability.extract_trace(request.headers)
        enriched_meta = dict(meta)
        enriched_meta["traceId"] = trace.trace_id
        enriched_meta["spanId"] = trace.span_id

        return await self.scheduler.submit_frame(
            frame_bytes=frame_bytes,
            meta=enriched_meta,
            trace_id=trace.trace_id,
            span_id=trace.span_id,
        )

    async def emit_degradation_changes(
        self,
        seq: int,
        ts_capture_ms: int,
        ttl_ms: int,
        trace_id: str,
        span_id: str,
    ) -> None:
        changes = self.degradation.consume_state_changes()
        for change in changes:
            if change.current == DegradationState.SAFE_MODE:
                status = "gateway_safe_mode"
            elif change.current == DegradationState.DEGRADED:
                status = "gateway_degraded"
            else:
                status = "gateway_normal"

            health_event = EventEnvelope(
                type=EventType.HEALTH,
                traceId=trace_id,
                spanId=span_id,
                seq=seq,
                tsCaptureMs=ts_capture_ms,
                ttlMs=ttl_ms,
                coordFrame=CoordFrame.WORLD,
                confidence=1.0,
                priority=self.config.health_priority,
                source="degradation@v1",
                payload={"status": status, "reason": change.reason},
            )
            await self._emit_event(health_event)

    async def _on_lane_results(self, frame: FrameInput, lane: ToolLane, results: list[Any]) -> None:
        trace_id = str(frame.meta.get("traceId", "0" * 32))
        span_id = str(frame.meta.get("spanId", "0" * 16))
        fused = self.fusion.fuse_lane(frame=frame, lane=lane, results=results, trace_id=trace_id, span_id=span_id)

        now = _now_ms()
        decision = self.safety.adjudicate(fused.events, now_ms=now)
        for event in decision.events:
            if event.is_expired(now):
                self.metrics.inc_deadline_miss(lane.value)
                continue
            self.metrics.observe_e2e_latency(max(0, now - event.tsCaptureMs))
            await self._emit_event(event)

        await self.emit_degradation_changes(
            seq=frame.seq,
            ts_capture_ms=frame.ts_capture_ms,
            ttl_ms=frame.ttl_ms,
            trace_id=trace_id,
            span_id=span_id,
        )

    async def _emit_event(self, event: EventEnvelope) -> None:
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
