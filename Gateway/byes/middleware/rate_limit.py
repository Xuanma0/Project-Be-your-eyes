from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qs


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool
    requests_per_second: float
    burst: int
    key_mode: str


@dataclass
class _BucketState:
    tokens: float
    updated_at: float


class RateLimitMiddleware:
    def __init__(
        self,
        app,
        *,
        config: RateLimitConfig,
    ) -> None:
        self.app = app
        self.config = config
        self._lock = threading.Lock()
        self._buckets: dict[str, _BucketState] = {}
        self._cleanup_cursor = 0
        self._skip_paths = {"/api/health", "/api/external_readiness", "/metrics"}

    @staticmethod
    def _json_response_bytes(status: int, payload: dict[str, str], retry_after: str | None = None) -> tuple[dict, dict]:
        body = json.dumps(payload).encode("utf-8")
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if retry_after:
            headers.append((b"retry-after", retry_after.encode("ascii")))
        return (
            {"type": "http.response.start", "status": status, "headers": headers},
            {"type": "http.response.body", "body": body, "more_body": False},
        )

    @staticmethod
    def _query_value(scope, name: str) -> str:  # type: ignore[no-untyped-def]
        raw = bytes(scope.get("query_string", b"")).decode("utf-8", errors="ignore")
        parsed = parse_qs(raw, keep_blank_values=True)
        values = parsed.get(name) or []
        if not values:
            return ""
        return str(values[0]).strip()

    @staticmethod
    def _header_value(scope, header_name: bytes) -> str:  # type: ignore[no-untyped-def]
        for key, value in list(scope.get("headers", [])):
            if bytes(key).lower() == header_name:
                return bytes(value).decode("utf-8", errors="ignore").strip()
        return ""

    def _client_ip(self, scope) -> str:  # type: ignore[no-untyped-def]
        client = scope.get("client")
        if isinstance(client, tuple) and client:
            host = str(client[0]).strip()
            if host:
                return host
        return "unknown"

    @staticmethod
    def _hash_secret(value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return digest[:24]

    def _key_for_scope(self, scope) -> str:  # type: ignore[no-untyped-def]
        key_mode = str(self.config.key_mode or "ip").strip().lower()
        if key_mode == "api_key_or_ip":
            api_key = self._header_value(scope, b"x-byes-api-key") or self._query_value(scope, "api_key")
            if api_key:
                return f"api:{self._hash_secret(api_key)}"
        return f"ip:{self._client_ip(scope)}"

    def _allow(self, key: str) -> tuple[bool, float]:
        now = time.monotonic()
        rps = max(0.01, float(self.config.requests_per_second))
        burst = max(1, int(self.config.burst))

        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                state = _BucketState(tokens=float(burst), updated_at=now)

            elapsed = max(0.0, now - state.updated_at)
            state.tokens = min(float(burst), state.tokens + elapsed * rps)
            state.updated_at = now

            if state.tokens >= 1.0:
                state.tokens -= 1.0
                self._buckets[key] = state
                self._cleanup_cursor += 1
                if self._cleanup_cursor % 512 == 0:
                    self._prune(now, max_idle_sec=max(60.0, float(burst) / rps * 8.0))
                return True, 0.0

            self._buckets[key] = state
            wait_sec = (1.0 - state.tokens) / rps
            return False, max(0.0, wait_sec)

    def _prune(self, now: float, max_idle_sec: float) -> None:
        stale = [key for key, state in self._buckets.items() if (now - state.updated_at) > max_idle_sec]
        for key in stale:
            self._buckets.pop(key, None)

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        if not bool(self.config.enabled):
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET")).upper()
        if method == "OPTIONS" or path in self._skip_paths:
            await self.app(scope, receive, send)
            return

        key = self._key_for_scope(scope)
        allowed, wait_sec = self._allow(key)
        if allowed:
            await self.app(scope, receive, send)
            return

        retry_after = str(max(1, int(wait_sec + 0.999)))
        start, body = self._json_response_bytes(429, {"detail": "Too Many Requests"}, retry_after)
        await send(start)
        await send(body)

