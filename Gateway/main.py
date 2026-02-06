from fastapi import FastAPI
from pydantic import BaseModel
import time

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

@app.get("/api/health")
def health():
    return {"ok": True, "ts": int(time.time() * 1000)}

@app.get("/api/mock_event", response_model=MockEvent)
def mock_event():
    global _flip
    now_ms = int(time.time() * 1000)
    _flip = not _flip
    if _flip:
        return MockEvent(
            type="risk",
            timestampMs=now_ms,
            coordFrame="World",
            confidence=0.9,
            ttlMs=3000,
            source="gateway",
            riskText="前方有障碍",
            distanceM=1.5,
            azimuthDeg=0.0,
        )
    else:
        return MockEvent(
            type="perception",
            timestampMs=now_ms,
            coordFrame="World",
            confidence=0.9,
            ttlMs=3000,
            source="gateway",
            summary="检测到门",
        )
