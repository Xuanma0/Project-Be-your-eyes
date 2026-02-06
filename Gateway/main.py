import asyncio
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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


_flip = False


def _build_event(is_risk: bool, source: str, now_ms: int) -> MockEvent:
    if is_risk:
        return MockEvent(
            type="risk",
            timestampMs=now_ms,
            coordFrame="World",
            confidence=0.9,
            ttlMs=3000,
            source=source,
            riskText="前方有障碍",
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
        summary="检测到门",
    )


def _to_dict(model: MockEvent) -> dict:
    # pydantic v1/v2 compatibility
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


@app.get("/api/health")
def health():
    return {"ok": True, "ts": int(time.time() * 1000)}


@app.get("/api/mock_event", response_model=MockEvent)
def mock_event():
    global _flip
    _flip = not _flip
    now_ms = int(time.time() * 1000)
    return _build_event(_flip, "gateway", now_ms)


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    ws_flip = False
    ping_msg = "__ping__"
    pong_msg = "__pong__"

    async def send_events() -> None:
        nonlocal ws_flip
        while True:
            ws_flip = not ws_flip
            now_ms = int(time.time() * 1000)
            event = _build_event(ws_flip, "gateway_ws", now_ms)
            await websocket.send_json(_to_dict(event))
            await asyncio.sleep(1.0)

    async def receive_and_pong() -> None:
        while True:
            message = await websocket.receive_text()
            if message == ping_msg:
                await websocket.send_text(pong_msg)

    send_task = asyncio.create_task(send_events())
    recv_task = asyncio.create_task(receive_and_pong())

    try:
        done, pending = await asyncio.wait(
            {send_task, recv_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            ex = task.exception()
            if ex is not None:
                return
    except WebSocketDisconnect:
        return
