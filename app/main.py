from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import AssistanceAgent
from .asr import AudioTranscriber
from .config import settings
from .evidence import EvidenceStore
from .planner import Planner
from .tracker_sidecar import TrackerSidecarClient
from .voice_sidecar import VoiceSidecarClient
from .vision import VisionToolchain


STATIC_DIR = settings.root_dir / "static"


class AnalyzeRequest(BaseModel):
    image_data: str = ""
    question: str = ""
    mode: str = "ask"


class TranscribeRequest(BaseModel):
    audio_data: str = ""


class TTSRequest(BaseModel):
    text: str = ""
    rate: float = 1.0


class CameraSelectRequest(BaseModel):
    index: int = 0


class TrackRequest(BaseModel):
    image_data: str = ""
    bbox: Optional[list[float]] = None
    label: str = ""
    reset: bool = False


class TranscribeResponse(BaseModel):
    text: str
    language: str
    language_probability: float
    latency_ms: float
    model: str


class AnalyzeResponse(BaseModel):
    action: str
    speech: str
    confidence: float
    plan: Dict[str, Any]
    quality: Dict[str, Any]
    safety: Dict[str, Any]
    evidence: list[Dict[str, Any]]
    memory: list[Dict[str, Any]]
    stats: Dict[str, Any]
    annotated_image: str
    planner: str
    agent: Dict[str, Any]


app = FastAPI(title="Be Your Eyes Prototype")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

vision = VisionToolchain()
planner = Planner()
agent = AssistanceAgent()
transcriber = AudioTranscriber()
voice_sidecar = VoiceSidecarClient()
tracker_sidecar = TrackerSidecarClient()
store = EvidenceStore(settings.log_dir / "evidence.jsonl", max_items=settings.evidence_max_items)


@app.on_event("startup")
def startup() -> None:
    vision._ensure_camera_thread()
    vision.warmup_async()


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status() -> Dict[str, Any]:
    return {
        "ok": True,
        "time": time.time(),
        "deepseek_enabled": planner.enabled,
        "deepseek_model": settings.deepseek_model,
        "yolo_model": settings.yolo_model,
        "base_yolo_mode": settings.base_yolo_mode,
        "yoloe_model": settings.yoloe_model,
        "yolo_world_model": settings.yolo_world_model,
        "yoloe": vision.yoloe_status(),
        "open_vocab": vision.open_vocab_status(),
        "depth": vision.depth_status(),
        "sam3": vision.sam3_status(),
        "hand_tracking": vision.hand_status(),
        "camera": vision.camera_status(),
        "asr": transcriber.status(),
        "voice_sidecar": voice_sidecar.status(),
        "tracker_sidecar": tracker_sidecar.status(),
        "agent": agent.status(),
        "log_path": str(settings.log_dir / "evidence.jsonl"),
    }


@app.post("/api/transcribe", response_model=TranscribeResponse)
def transcribe(req: TranscribeRequest) -> TranscribeResponse:
    if not req.audio_data:
        raise HTTPException(status_code=400, detail="audio_data is required")
    try:
        try:
            result = voice_sidecar.transcribe_data_url(req.audio_data)
        except Exception:
            result = transcriber.transcribe_data_url(req.audio_data)
        return TranscribeResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=repr(exc)) from exc


@app.get("/api/tracker/status")
def tracker_status() -> Dict[str, Any]:
    return tracker_sidecar.status()


@app.post("/api/tracker/reset")
def tracker_reset() -> Dict[str, Any]:
    try:
        return tracker_sidecar.reset()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=repr(exc)) from exc


@app.post("/api/track")
def track(req: TrackRequest) -> Dict[str, Any]:
    if not req.image_data:
        raise HTTPException(status_code=400, detail="image_data is required")
    try:
        return tracker_sidecar.track(
            image_data=req.image_data,
            bbox=req.bbox,
            label=req.label,
            reset=req.reset,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=repr(exc)) from exc


@app.post("/api/tts")
def tts(req: TTSRequest) -> Response:
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        audio, media_type, engine = voice_sidecar.tts(text, req.rate)
        return Response(
            content=audio,
            media_type=media_type,
            headers={"X-TTS-Engine": engine, "X-TTS-Rate-Applied": "1"},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=repr(exc)) from exc


@app.post("/api/voice/warmup")
def voice_warmup() -> Dict[str, Any]:
    try:
        return voice_sidecar.warmup_asr()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=repr(exc)) from exc


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if not req.image_data:
        raise HTTPException(status_code=400, detail="image_data is required")
    question = req.question.strip()
    mode = req.mode.strip() or "ask"
    try:
        frame = vision.capture_server_frame() if req.image_data == "server_camera" else vision.decode_image(req.image_data)
        plan = planner.plan_tools(question, mode)
        result = vision.analyze(frame, plan)
        current = store.add_many(result["evidence"])
        current_dicts = [item.to_dict() for item in current]
        memory = store.memory(limit=80) if "memory" in plan.get("tools", []) or mode == "memory" else store.recent(limit=60)
        agent_context = agent.update(
            question=question,
            mode=mode,
            plan=plan,
            current_evidence=current_dicts,
            recent_evidence=memory,
            quality=result["quality"],
            safety=result["safety"],
        )
        evidence_for_answer = agent_context["evidence"]
        answer = planner.compose_answer(
            question=question,
            mode=mode,
            plan=plan,
            current_evidence=evidence_for_answer,
            memory=memory,
            safety=result["safety"],
            quality=result["quality"],
        )
        answer = agent.refine_answer(answer, mode, agent_context["agent"])
        return AnalyzeResponse(
            action=answer["action"],
            speech=answer["speech"],
            confidence=float(answer.get("confidence", 0.0)),
            plan=plan,
            quality=result["quality"],
            safety=result["safety"],
            evidence=evidence_for_answer,
            memory=memory[-30:],
            stats=result["stats"],
            annotated_image=result["annotated_image"],
            planner=str(answer.get("planner", "unknown")),
            agent=answer.get("agent", agent_context["agent"]),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=repr(exc)) from exc


@app.get("/api/evidence")
def evidence(include_expired: bool = False) -> Dict[str, Any]:
    return {"items": store.recent(include_expired=include_expired, limit=120)}


@app.get("/api/server-camera/frame.jpg")
def server_camera_frame() -> Response:
    frame = vision.capture_server_frame()
    return Response(
        content=vision.jpeg_bytes(frame, width=settings.stream_width, quality=74).tobytes(),
        media_type="image/jpeg",
    )


@app.post("/api/server-camera/select")
def select_server_camera(req: CameraSelectRequest) -> Dict[str, Any]:
    try:
        return {"ok": True, "camera": vision.set_camera_index(int(req.index))}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=repr(exc)) from exc


@app.post("/api/server-camera/stop")
def stop_server_camera() -> Dict[str, Any]:
    vision.stop_camera()
    return {"ok": True, "camera": vision.camera_status()}


@app.get("/api/server-camera/stream.mjpg")
def server_camera_stream() -> StreamingResponse:
    def frames():
        while True:
            try:
                frame = vision.capture_server_frame()
                payload = vision.jpeg_bytes(frame, width=settings.stream_width, quality=72).tobytes()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-cache\r\n\r\n"
                    + payload
                    + b"\r\n"
                )
                time.sleep(1 / max(1.0, settings.stream_fps))
            except Exception:
                time.sleep(0.2)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/reset")
def reset() -> Dict[str, Any]:
    store.clear()
    agent.reset()
    try:
        tracker_sidecar.reset()
    except Exception:
        pass
    return {"ok": True}
