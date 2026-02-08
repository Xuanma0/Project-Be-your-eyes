from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def now_ms() -> int:
    return int(time.time() * 1000)


class EventType(str, Enum):
    PERCEPTION = "perception"
    RISK = "risk"
    NAVIGATION = "navigation"
    DIALOG = "dialog"
    HEALTH = "health"
    ACTION_PLAN = "action_plan"


class CoordFrame(str, Enum):
    CAMERA = "Camera"
    DEVICE = "Device"
    WORLD = "World"
    MAP = "Map"
    ANCHOR = "Anchor"


class HealthStatus(str, Enum):
    NORMAL = "NORMAL"
    THROTTLED = "THROTTLED"
    DEGRADED = "DEGRADED"
    SAFE_MODE = "SAFE_MODE"
    WAITING_CLIENT = "WAITING_CLIENT"


class Intrinsics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int


class Position3(BaseModel):
    model_config = ConfigDict(extra="ignore")

    x: float
    y: float
    z: float


class RotationQuat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    x: float
    y: float
    z: float
    w: float


class Pose(BaseModel):
    model_config = ConfigDict(extra="ignore")

    position: Position3 | None = None
    rotation: RotationQuat | None = None


class FrameMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    frameSeq: int | None = None
    deviceTsMs: int | None = None
    unityTsMs: int | None = None
    coordFrame: CoordFrame | None = None
    intrinsics: Intrinsics | None = None
    pose: Pose | None = None
    note: str | None = None

    @field_validator("coordFrame", mode="before")
    @classmethod
    def _normalize_coord_frame(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, CoordFrame):
            return value
        raw = str(value).strip()
        if not raw:
            return None
        for coord in CoordFrame:
            if raw.lower() == coord.value.lower() or raw.lower() == coord.name.lower():
                return coord
        raise ValueError(f"invalid coordFrame: {value}")

    def is_empty(self) -> bool:
        return not any(
            [
                self.frameSeq is not None,
                self.deviceTsMs is not None,
                self.unityTsMs is not None,
                self.coordFrame is not None,
                self.intrinsics is not None,
                self.pose is not None,
                bool(self.note),
            ]
        )


class EventEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EventType
    traceId: str = Field(default_factory=lambda: secrets.token_hex(16))
    spanId: str = Field(default_factory=lambda: secrets.token_hex(8))
    seq: int
    tsCaptureMs: int
    tsEmitMs: int = Field(default_factory=now_ms)
    ttlMs: int = 3000
    coordFrame: CoordFrame = CoordFrame.WORLD
    confidence: float = 0.0
    priority: int = 0
    source: str
    healthStatus: HealthStatus | None = None
    healthReason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @field_validator("ttlMs")
    @classmethod
    def _ttl_positive(cls, value: int) -> int:
        return value if value > 0 else 1

    def is_expired(self, now: int | None = None) -> bool:
        current = now if now is not None else now_ms()
        return current - self.tsCaptureMs > self.ttlMs


class ActionType(str, Enum):
    STOP = "stop"
    SCAN = "scan"
    CONFIRM = "confirm"
    TURN = "turn"
    MOVE = "move"
    FIND = "find"


class ActionStep(BaseModel):
    action: ActionType
    text: str | None = None
    distanceM: float | None = None
    azimuthDeg: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ActionPlan(BaseModel):
    planId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    traceId: str
    tsEmitMs: int = Field(default_factory=now_ms)
    expiresMs: int
    mode: str
    overallConfidence: float = 0.0
    steps: list[ActionStep] = Field(default_factory=list)
    fallback: str | None = None

    @field_validator("overallConfidence")
    @classmethod
    def _plan_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class DepthHazard(BaseModel):
    distanceM: float
    azimuthDeg: float
    confidence: float
    kind: str

    @field_validator("confidence")
    @classmethod
    def _hazard_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class DepthResult(BaseModel):
    hazards: list[DepthHazard] = Field(default_factory=list)
    model: str | None = None
    latencyMs: int | None = None


class ToolStatus(str, Enum):
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"
    CANCELLED = "cancelled"
    DROPPED_EXPIRED = "dropped_expired"


class ToolResult(BaseModel):
    toolName: str
    toolVersion: str
    seq: int
    tsCaptureMs: int
    latencyMs: int
    confidence: float = 0.0
    coordFrame: CoordFrame = CoordFrame.WORLD
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ToolStatus = ToolStatus.OK
    error: str | None = None

    @field_validator("confidence")
    @classmethod
    def _tool_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


LegacyEventType = Literal["risk", "perception", "health", "action_plan"]


class LegacyEvent(BaseModel):
    type: LegacyEventType
    seq: int | None = None
    timestampMs: int
    coordFrame: str = "World"
    confidence: float
    ttlMs: int
    source: str
    stage: str | None = None
    riskText: str | None = None
    summary: str | None = None
    distanceM: float | None = None
    azimuthDeg: float | None = None
    hazardId: str | None = None
    hazardKind: str | None = None
    hazardState: Literal["new", "active", "persisted"] | None = None
    activeConfirm: bool | None = None
    crosscheckKind: str | None = None
    healthStatus: HealthStatus | None = None
    healthReason: str | None = None
