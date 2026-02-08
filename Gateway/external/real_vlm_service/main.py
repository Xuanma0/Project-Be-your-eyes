from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class RealVlmRequest(BaseModel):
    sessionId: str | None = None
    question: str | None = None
    seq: int | None = None
    tsCaptureMs: int | None = None
    ttlMs: int | None = None
    frameMeta: dict[str, Any] | None = None
    coordFrame: str | None = None


class ActionPlanPayload(BaseModel):
    summary: str
    speech: str
    hud: list[str]
    priority: int = 40
    confidence: float = 0.82
    tags: list[str]
    steps: list[dict[str, Any]]
    fallback: str = "confirm"
    mode: str = "ask"


class RealVlmResponse(BaseModel):
    answerText: str
    actionPlan: ActionPlanPayload
    diagnostics: dict[str, Any]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


app = FastAPI(title="BeYourEyes RealVLM Service")
_SERVICE_VERSION = "0.2.1"
_STATE: dict[str, Any] = {
    "ready": False,
    "warmed_up": False,
    "model_id": "",
    "backend": "mock",
    "version": _SERVICE_VERSION,
}


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return str(raw).strip() if raw is not None else default


def _build_runtime_state() -> dict[str, Any]:
    backend = _env_str("BYES_BACKEND", "mock").lower()
    model_id = _env_str("BYES_MODEL_ID", "byes-real-vlm-v1")
    _weights_dir = _env_str("BYES_WEIGHTS_DIR", "/models")
    ready = backend in {"mock", "torch", "onnx"}
    warmed_up = ready
    return {
        "ready": ready,
        "warmed_up": warmed_up,
        "model_id": model_id,
        "backend": backend,
        "version": _SERVICE_VERSION,
    }


@app.on_event("startup")
async def _startup() -> None:
    _STATE.update(_build_runtime_state())


def _ensure_ready() -> None:
    if not bool(_STATE.get("ready", False)):
        raise HTTPException(status_code=503, detail="service_not_ready")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "real_vlm", "ts": int(time.time() * 1000)}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "ready": bool(_STATE.get("ready", False)),
        "model_id": str(_STATE.get("model_id", "")),
        "backend": str(_STATE.get("backend", "mock")),
        "version": str(_STATE.get("version", _SERVICE_VERSION)),
        "warmed_up": bool(_STATE.get("warmed_up", False)),
    }


@app.post("/infer/real_vlm")
async def infer_real_vlm(request: RealVlmRequest) -> dict[str, Any]:
    _ensure_ready()
    started = time.perf_counter()

    fail_prob = max(0.0, min(1.0, _env_float("VLM_FAIL_PROB", 0.0)))
    if fail_prob > 0 and random.random() < fail_prob:
        await asyncio.sleep(0.01)
        return {"answerText": "", "actionPlan": {}, "diagnostics": {"error": "simulated_failure"}}

    sleep_ms = max(0, _env_int("VLM_SLEEP_MS", 140))
    if sleep_ms > 0:
        await asyncio.sleep(sleep_ms / 1000.0)

    question = (request.question or "what is in front of me?").strip()
    answer = "I can see a doorway ahead. Please proceed carefully and confirm the path."

    plan = ActionPlanPayload(
        summary="VLM guidance ready",
        speech=f"Question: {question}. {answer}",
        hud=["Doorway ahead", "Proceed carefully", "Confirm before moving"],
        tags=["real_vlm", "ask"],
        steps=[
            {"action": "confirm", "text": "Confirm doorway is clear."},
            {"action": "scan", "text": "Scan left and right for obstacles."},
        ],
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
    response = RealVlmResponse(
        answerText=answer,
        actionPlan=plan,
        diagnostics={
            "latencyMs": latency_ms,
            "question": question,
            "sessionId": request.sessionId or "default",
        },
    )
    return response.model_dump(mode="json")
