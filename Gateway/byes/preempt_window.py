from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PreemptWindow:
    active_until_ms: int = -1
    last_reason: str = "critical_risk"

    def enter(self, now_ms: int, duration_ms: int, reason: str = "critical_risk") -> bool:
        was_active = self.is_active(now_ms)
        self.last_reason = reason
        next_until = int(now_ms) + max(1, int(duration_ms))
        if next_until > self.active_until_ms:
            self.active_until_ms = next_until
        return not was_active

    def is_active(self, now_ms: int) -> bool:
        if self.active_until_ms < 0:
            return False
        if int(now_ms) < self.active_until_ms:
            return True
        self.active_until_ms = -1
        return False

    def reset_runtime(self) -> None:
        self.active_until_ms = -1
        self.last_reason = "critical_risk"
