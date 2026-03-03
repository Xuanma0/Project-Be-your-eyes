from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="BYES optional pySLAM service")


class SlamStepRequest(BaseModel):
    image_b64: str
    tsMs: int | None = None
    deviceId: str | None = None
    intrinsics: dict[str, Any] | None = None


class _State:
    def __init__(self) -> None:
        self.count = 0
        self.started_ms = int(time.time() * 1000)


state = _State()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "pyslam_service", "uptimeSec": max(0, int((time.time() * 1000 - state.started_ms) / 1000))}


@app.post("/slam/reset")
def slam_reset() -> dict[str, Any]:
    state.count = 0
    return {"ok": True, "reset": True}


@app.post("/slam/step")
def slam_step(request: SlamStepRequest) -> dict[str, Any]:
    if not str(request.image_b64 or "").strip():
        raise HTTPException(status_code=400, detail="empty_image_b64")

    state.count += 1
    idx = int(state.count)
    return {
        "ok": True,
        "schemaVersion": "byes.slam_pose.v1",
        "frameSeq": idx,
        "trackingState": "tracking",
        "pose": {
            "t": [round(0.05 * idx, 4), 0.0, 0.0],
            "q": [0.0, 0.0, 0.0, 1.0],
        },
        "backend": "pyslam_http",
        "model": "pyslam-proxy",
        "endpoint": "/slam/step",
    }
