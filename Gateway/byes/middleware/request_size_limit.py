from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RequestSizeLimits:
    frame_bytes: int
    runpackage_zip_bytes: int
    json_bytes: int


class _PayloadTooLargeError(Exception):
    pass


class RequestSizeLimitMiddleware:
    def __init__(
        self,
        app,
        *,
        limits: RequestSizeLimits,
    ) -> None:
        self.app = app
        self.limits = limits

    def _resolve_limit(self, method: str, path: str) -> int:
        verb = str(method or "").upper()
        if verb in {"GET", "HEAD", "OPTIONS"}:
            return 0
        normalized = str(path or "").strip()
        if normalized.startswith("/api/frame"):
            return max(0, int(self.limits.frame_bytes))
        if normalized == "/api/run_package/upload":
            return max(0, int(self.limits.runpackage_zip_bytes))
        if verb in {"POST", "PUT", "PATCH"}:
            return max(0, int(self.limits.json_bytes))
        return 0

    @staticmethod
    def _content_length(headers: list[tuple[bytes, bytes]]) -> int | None:
        for key, value in headers:
            if bytes(key).lower() != b"content-length":
                continue
            raw = bytes(value).decode("utf-8", errors="ignore").strip()
            if not raw:
                return None
            try:
                return int(raw)
            except ValueError:
                return None
        return None

    @staticmethod
    async def _send_413(send: Callable) -> None:
        body = json.dumps({"detail": "Payload Too Large"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET"))
        limit = self._resolve_limit(method, path)
        if limit <= 0:
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(list(scope.get("headers", [])))
        if content_length is not None and content_length > limit:
            await self._send_413(send)
            return

        consumed = 0

        async def _limited_receive():  # type: ignore[no-untyped-def]
            nonlocal consumed
            message = await receive()
            if message.get("type") != "http.request":
                return message
            body = bytes(message.get("body", b""))
            consumed += len(body)
            if consumed > limit:
                raise _PayloadTooLargeError()
            return message

        try:
            await self.app(scope, _limited_receive, send)
        except _PayloadTooLargeError:
            await self._send_413(send)

