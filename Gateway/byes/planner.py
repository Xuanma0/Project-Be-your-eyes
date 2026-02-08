from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from byes.config import GatewayConfig
from byes.degradation import DegradationState
from byes.tool_registry import ToolDescriptor
from byes.tools.base import ToolLane


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class FrameContext:
    seq: int
    ts_capture_ms: int
    ttl_ms: int
    meta: dict[str, Any]


@dataclass(frozen=True)
class RecentFrameSummary:
    seq: int
    completed_at_ms: int
    outcome: str
    invoked: int = 0
    timeout: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ToolInvocation:
    tool_name: str
    lane: ToolLane
    timeout_ms: int
    priority: int


@dataclass(frozen=True)
class ToolInvocationPlan:
    seq: int
    generated_at_ms: int
    fast_budget_ms: int
    slow_budget_ms: int
    invocations: list[ToolInvocation] = field(default_factory=list)

    def lane_invocations(self, lane: ToolLane) -> list[ToolInvocation]:
        return [item for item in self.invocations if item.lane == lane]


class PolicyPlannerV0:
    """Rule-based planner for v0 intelligent enhancement."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config

    def plan(
        self,
        frame: FrameContext,
        degradation_state: DegradationState,
        recent: list[RecentFrameSummary],
        tools: list[ToolDescriptor],
    ) -> ToolInvocationPlan:
        active_intent = str(frame.meta.get("intent", "none")).strip().lower()
        _ = recent
        invocations: list[ToolInvocation] = []

        fast_tools = [tool for tool in tools if tool.lane == ToolLane.FAST.value]
        slow_tools = [tool for tool in tools if tool.lane == ToolLane.SLOW.value]

        for tool in sorted(fast_tools, key=lambda item: self._priority_for(item), reverse=True):
            invocations.append(
                ToolInvocation(
                    tool_name=tool.name,
                    lane=ToolLane.FAST,
                    timeout_ms=min(tool.timeoutMs, self._config.fast_budget_ms),
                    priority=self._priority_for(tool),
                )
            )

        if degradation_state not in {DegradationState.SAFE_MODE, DegradationState.DEGRADED}:
            for tool in sorted(slow_tools, key=lambda item: self._priority_for(item), reverse=True):
                if tool.name == "real_ocr" and active_intent != "scan_text":
                    continue
                invocations.append(
                    ToolInvocation(
                        tool_name=tool.name,
                        lane=ToolLane.SLOW,
                        timeout_ms=min(tool.timeoutMs, self._config.slow_budget_ms),
                        priority=self._priority_for(tool),
                    )
                )

        return ToolInvocationPlan(
            seq=frame.seq,
            generated_at_ms=_now_ms(),
            fast_budget_ms=self._config.fast_budget_ms,
            slow_budget_ms=self._config.slow_budget_ms,
            invocations=invocations,
        )

    @staticmethod
    def _priority_for(tool: ToolDescriptor) -> int:
        capability = tool.capability.lower()
        if capability == "risk":
            return 1000
        if capability == "det":
            return 300
        if capability == "ocr":
            return 250
        return 100
