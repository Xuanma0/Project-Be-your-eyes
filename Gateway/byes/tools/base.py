from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

from byes.schema import ToolResult


class ToolLane(str, Enum):
    FAST = "fast"
    SLOW = "slow"


@dataclass(frozen=True)
class ToolContext:
    trace_id: str
    span_id: str
    deadline_ms: int
    meta: dict[str, Any]


@dataclass(frozen=True)
class FrameInput:
    seq: int
    ts_capture_ms: int
    ttl_ms: int
    frame_bytes: bytes
    meta: dict[str, Any]


class BaseTool(ABC):
    name: str
    version: str
    lane: ToolLane
    p95_budget_ms: int
    timeout_ms: int
    degradable: bool
    capability: str

    @abstractmethod
    async def infer(self, frame: FrameInput, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError
