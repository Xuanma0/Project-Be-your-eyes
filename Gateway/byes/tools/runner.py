from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class MultiModelRequest:
    frame_bytes: bytes
    roi: dict[str, Any] | None = None
    tasks: list[str] = field(default_factory=list)


class ToolRunner(ABC):
    @abstractmethod
    async def infer_bundle(self, request: MultiModelRequest, timeout_ms: int) -> dict[str, Any]:
        """Run one network call that may execute multiple model tasks server-side."""
        raise NotImplementedError


class HttpToolRunner(ToolRunner):
    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint

    async def infer_bundle(self, request: MultiModelRequest, timeout_ms: int) -> dict[str, Any]:
        files = {
            "image": ("frame.jpg", request.frame_bytes, "image/jpeg"),
        }
        data: dict[str, str] = {
            "tasks": json.dumps(request.tasks),
        }
        if request.roi is not None:
            data["roi"] = json.dumps(request.roi)

        timeout_s = max(0.05, timeout_ms / 1000.0)
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(self._endpoint, files=files, data=data)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("runner response must be a JSON object")
        return payload
