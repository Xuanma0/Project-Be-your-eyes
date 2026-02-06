import asyncio
import time
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

app = FastAPI(title="BeYourEyes Gateway")


class MockEvent(BaseModel):
    type: str  # "risk" or "perception"
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
            except Exception:
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
            except Exception:
                failed.append(ws)

        if failed:
            async with self._lock:
                for ws in failed:
                    self.active.discard(ws)


manager = ConnectionManager()
_flip = False


def _to_dict(model: MockEvent) -> dict:
    # pydantic v1/v2 compatibility
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _build_event(is_risk: bool, source: str, now_ms: int) -> MockEvent:
    if is_risk:
        return MockEvent(
            type="risk",
            timestampMs=now_ms,
            coordFrame="World",
            confidence=0.9,
            ttlMs=3000,
            source=source,
            riskText="\u524d\u65b9\u6709\u969c\u788d",
            distanceM=1.5,
            azimuthDeg=0.0,
        )

    return MockEvent(
        type="perception",
        timestampMs=now_ms,
        coordFrame="World",
        confidence=0.9,
        ttlMs=3000,
        source=source,
        summary="\u68c0\u6d4b\u5230\u95e8",
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ts": int(time.time() * 1000)}


@app.get("/api/mock_event", response_model=MockEvent)
def mock_event() -> MockEvent:
    global _flip
    _flip = not _flip
    now_ms = int(time.time() * 1000)
    return _build_event(_flip, "gateway", now_ms)


@app.post("/api/frame")
async def frame(image: UploadFile = File(...), meta: str | None = Form(None)) -> dict[str, Any]:
    _ = meta
    frame_bytes = await image.read()
    now_ms = int(time.time() * 1000)

    perception_start = MockEvent(
        type="perception",
        timestampMs=now_ms,
        coordFrame="World",
        confidence=0.9,
        ttlMs=3000,
        source="gateway",
        summary="\u6536\u5230\u5e27\uff0c\u6b63\u5728\u8bc6\u522b...",
    )
    await manager.broadcast_json(_to_dict(perception_start))

    await asyncio.sleep(0.2)

    perception_done = MockEvent(
        type="perception",
        timestampMs=int(time.time() * 1000),
        coordFrame="World",
        confidence=0.9,
        ttlMs=3000,
        source="gateway",
        summary="\u68c0\u6d4b\u5230\u95e8",
    )
    await manager.broadcast_json(_to_dict(perception_done))

    return {"ok": True, "bytes": len(frame_bytes)}


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await websocket.accept()
    await manager.connect(websocket)

    try:
        while True:
            message = await websocket.receive_text()
            if message == "__ping__":
                await websocket.send_text("__pong__")
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
