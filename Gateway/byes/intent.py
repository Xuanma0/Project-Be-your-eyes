from __future__ import annotations

import time
from dataclasses import dataclass


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class IntentSnapshot:
    intent: str
    question: str | None
    expires_at_ms: int

    @property
    def active(self) -> bool:
        return self.intent != "none"


class IntentManager:
    """Keeps short-lived runtime intent flags for planner gating."""

    def __init__(self) -> None:
        self._intent = "none"
        self._question: str | None = None
        self._expires_at_ms = -1

    def set_intent(self, intent: str, duration_ms: int, question: str | None = None) -> IntentSnapshot:
        normalized = intent.strip().lower() if intent else "none"
        if normalized == "none":
            self._intent = "none"
            self._question = None
            self._expires_at_ms = -1
            return self.snapshot()

        if normalized == "qa":
            normalized = "ask"

        normalized_question = None
        if question is not None:
            raw = str(question).strip()
            normalized_question = raw if raw else None

        if normalized == "ask" and not normalized_question:
            raise ValueError("ask intent requires a non-empty question")

        now_ms = _now_ms()
        ttl_ms = max(1, int(duration_ms))
        self._intent = normalized
        self._question = normalized_question if normalized in {"ask"} else None
        self._expires_at_ms = now_ms + ttl_ms
        return self.snapshot()

    def active_intent(self) -> str:
        now_ms = _now_ms()
        if self._expires_at_ms > 0 and now_ms >= self._expires_at_ms:
            self._intent = "none"
            self._question = None
            self._expires_at_ms = -1
        return self._intent

    def active_question(self) -> str | None:
        self.active_intent()
        if self._intent != "ask":
            return None
        return self._question

    def snapshot(self) -> IntentSnapshot:
        return IntentSnapshot(
            intent=self.active_intent(),
            question=self.active_question(),
            expires_at_ms=self._expires_at_ms,
        )

    def reset_runtime(self) -> None:
        self._intent = "none"
        self._question = None
        self._expires_at_ms = -1
