from __future__ import annotations

from dataclasses import dataclass

from byes.tools.base import BaseTool, ToolLane


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    version: str
    lane: str
    capability: str
    timeoutMs: int
    p95BudgetMs: int
    degradable: bool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_descriptors(self) -> list[ToolDescriptor]:
        descriptors = [
            ToolDescriptor(
                name=tool.name,
                version=tool.version,
                lane=tool.lane.value,
                capability=tool.capability,
                timeoutMs=tool.timeout_ms,
                p95BudgetMs=tool.p95_budget_ms,
                degradable=tool.degradable,
            )
            for tool in self._tools.values()
        ]
        return sorted(descriptors, key=lambda item: item.name)

    def lane_tools(self, lane: ToolLane, degraded: bool, safe_mode: bool) -> list[BaseTool]:
        lane_tools = [tool for tool in self._tools.values() if tool.lane == lane]
        if safe_mode:
            return [tool for tool in lane_tools if tool.capability == "risk"]
        if degraded and lane == ToolLane.SLOW:
            return []
        return lane_tools

    def all_lane_tools(self, lane: ToolLane) -> list[BaseTool]:
        return [tool for tool in self._tools.values() if tool.lane == lane]
