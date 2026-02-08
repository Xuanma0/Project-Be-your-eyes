from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from byes.schema import ConfirmRequest, ConfirmResponse


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class _PendingConfirm:
    request: ConfirmRequest
    expires_at_ms: int


class ConfirmManager:
    def __init__(
        self,
        *,
        metrics: object | None = None,
        default_ttl_ms: int = 5000,
        dedup_cooldown_ms: int = 4000,
    ) -> None:
        self._metrics = metrics
        self._default_ttl_ms = max(500, int(default_ttl_ms))
        self._dedup_cooldown_ms = max(0, int(dedup_cooldown_ms))
        self._pending_by_id: dict[str, _PendingConfirm] = {}
        self._last_ask_by_session_kind: dict[tuple[str, str], int] = {}
        self._last_resolved_request: ConfirmRequest | None = None
        self._last_resolved_response: ConfirmResponse | None = None
        self._set_pending_gauge()

    def create(
        self,
        kind: str,
        prompt: str,
        options: list[str] | None,
        ttl_ms: int,
        now_ms: int,
        session_id: str,
    ) -> ConfirmRequest | None:
        self.expire(now_ms)
        normalized_kind = str(kind or "").strip().lower()
        normalized_session = str(session_id or "").strip() or "default"
        normalized_prompt = str(prompt or "").strip()
        if not normalized_kind or not normalized_prompt:
            self._metric_call("inc_confirm_suppressed", "policy")
            return None

        dedup_key = (normalized_session, normalized_kind)
        pending_same = self.get_pending(normalized_session, kind=normalized_kind)
        if pending_same is not None:
            self._metric_call("inc_confirm_suppressed", "pending_exists")
            return None

        last_ask_ms = self._last_ask_by_session_kind.get(dedup_key, -1)
        if last_ask_ms >= 0 and int(now_ms) - last_ask_ms < self._dedup_cooldown_ms:
            self._metric_call("inc_confirm_suppressed", "cooldown")
            return None

        normalized_ttl_ms = max(500, int(ttl_ms)) if int(ttl_ms) > 0 else self._default_ttl_ms
        request = ConfirmRequest(
            confirmId=str(uuid.uuid4()),
            kind=normalized_kind,
            prompt=normalized_prompt,
            options=[str(item) for item in (options or ["yes", "no"])],
            ttlMs=normalized_ttl_ms,
            createdAtMs=int(now_ms),
            sessionId=normalized_session,
        )
        self._pending_by_id[request.confirmId] = _PendingConfirm(
            request=request,
            expires_at_ms=int(now_ms) + normalized_ttl_ms,
        )
        self._last_ask_by_session_kind[dedup_key] = int(now_ms)
        self._metric_call("inc_confirm_request", request.kind)
        self._set_pending_gauge()
        return request

    def resolve(self, confirm_id: str, answer: str, now_ms: int, source: str = "unknown") -> bool:
        self.expire(now_ms)
        key = str(confirm_id or "").strip()
        pending = self._pending_by_id.pop(key, None)
        self._set_pending_gauge()
        if pending is None:
            self._last_resolved_request = None
            self._last_resolved_response = None
            return False

        normalized_answer = self._normalize_answer(answer)
        response = ConfirmResponse(
            confirmId=key,
            answer=normalized_answer,
            respondedAtMs=int(now_ms),
            source=str(source or "unknown"),
        )
        self._last_resolved_request = pending.request
        self._last_resolved_response = response
        self._metric_call("inc_confirm_response", pending.request.kind, normalized_answer)
        return True

    def pop_last_resolution(self) -> tuple[ConfirmRequest | None, ConfirmResponse | None]:
        req = self._last_resolved_request
        resp = self._last_resolved_response
        self._last_resolved_request = None
        self._last_resolved_response = None
        return req, resp

    def get_pending(self, session_id: str, kind: str | None = None) -> ConfirmRequest | None:
        normalized_session = str(session_id or "").strip() or "default"
        normalized_kind = str(kind or "").strip().lower()
        candidates: list[ConfirmRequest] = []
        for pending in self._pending_by_id.values():
            request = pending.request
            if request.sessionId != normalized_session:
                continue
            if normalized_kind and request.kind != normalized_kind:
                continue
            candidates.append(request)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.createdAtMs)
        return candidates[0]

    def expire(self, now_ms: int) -> None:
        expired_ids: list[str] = []
        for confirm_id, pending in self._pending_by_id.items():
            if int(now_ms) >= int(pending.expires_at_ms):
                expired_ids.append(confirm_id)
        for confirm_id in expired_ids:
            pending = self._pending_by_id.pop(confirm_id, None)
            if pending is None:
                continue
            self._metric_call("inc_confirm_timeout", pending.request.kind)
        if expired_ids:
            self._set_pending_gauge()

    def reset_runtime(self) -> None:
        self._pending_by_id.clear()
        self._last_ask_by_session_kind.clear()
        self._last_resolved_request = None
        self._last_resolved_response = None
        self._set_pending_gauge()

    @property
    def pending_count(self) -> int:
        return len(self._pending_by_id)

    @staticmethod
    def _normalize_answer(answer: str) -> str:
        token = str(answer or "").strip().lower()
        if token in {"yes", "no", "unknown"}:
            return token
        if token in {"y", "true", "1"}:
            return "yes"
        if token in {"n", "false", "0"}:
            return "no"
        return "unknown"

    def _set_pending_gauge(self) -> None:
        self._metric_call("set_confirm_pending", len(self._pending_by_id))

    def _metric_call(self, method: str, *args: object) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)
