from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger("byes.faults")

_VALID_TOOLS = {"mock_risk", "mock_ocr", "real_det", "real_ocr", "real_depth", "all"}
_VALID_MODES = {"timeout", "slow", "low_conf", "disconnect"}


@dataclass
class FaultRule:
    tool: str
    mode: str
    value: Any
    expires_at_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "mode": self.mode,
            "value": self.value,
            "expiresAtMs": self.expires_at_ms,
        }


class FaultManager:
    def __init__(self, metrics: object | None = None) -> None:
        self._metrics = metrics
        self._rules: dict[tuple[str, str], FaultRule] = {}
        self._expiry_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def shutdown(self) -> None:
        async with self._lock:
            for task in self._expiry_tasks.values():
                task.cancel()
            self._expiry_tasks.clear()

    async def set_fault(self, tool: str, mode: str, value: Any, duration_ms: int | None = None) -> dict[str, Any]:
        self._validate(tool, mode)
        expires_at_ms = None
        if duration_ms is not None and duration_ms > 0:
            expires_at_ms = self._now_ms() + duration_ms

        key = (tool, mode)
        async with self._lock:
            self._rules[key] = FaultRule(tool=tool, mode=mode, value=value, expires_at_ms=expires_at_ms)
            old_task = self._expiry_tasks.pop(key, None)
            if old_task is not None:
                old_task.cancel()
            if duration_ms is not None and duration_ms > 0:
                self._expiry_tasks[key] = asyncio.create_task(self._expire_later(key, duration_ms))

        self._metric_call("inc_fault_set", tool, mode)
        LOGGER.warning("fault_set tool=%s mode=%s value=%s duration_ms=%s", tool, mode, value, duration_ms)
        return self.snapshot()

    async def clear_faults(self) -> dict[str, Any]:
        async with self._lock:
            self._rules.clear()
            for task in self._expiry_tasks.values():
                task.cancel()
            self._expiry_tasks.clear()
        LOGGER.warning("fault_clear all")
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        now_ms = self._now_ms()
        active = []
        for rule in list(self._rules.values()):
            if rule.expires_at_ms is not None and now_ms >= rule.expires_at_ms:
                continue
            active.append(rule.as_dict())
        return {"faults": active}

    def should_disconnect(self, tool_name: str) -> bool:
        value = self._effective_value(tool_name, "disconnect")
        if value is None:
            return False
        triggered = bool(value)
        if triggered:
            self._metric_call("inc_fault_trigger", tool_name, "disconnect")
        return triggered

    def should_timeout(self, tool_name: str) -> bool:
        value = self._effective_value(tool_name, "timeout")
        if value is None:
            return False

        trigger = False
        if isinstance(value, bool):
            trigger = value
        elif isinstance(value, (int, float)):
            numeric = float(value)
            if numeric <= 0:
                trigger = False
            elif numeric <= 1:
                trigger = random.random() < numeric
            elif numeric <= 100:
                trigger = random.random() < (numeric / 100.0)
            else:
                trigger = True
        else:
            trigger = False

        if trigger:
            self._metric_call("inc_fault_trigger", tool_name, "timeout")
        return trigger

    def extra_slow_delay_ms(self, tool_name: str) -> int:
        value = self._effective_value(tool_name, "slow")
        if value is None:
            return 0
        if not isinstance(value, (int, float)):
            return 0
        delay_ms = max(0, int(value))
        if delay_ms > 0:
            self._metric_call("inc_fault_trigger", tool_name, "slow")
        return delay_ms

    def low_conf_value(self, tool_name: str) -> float | None:
        value = self._effective_value(tool_name, "low_conf")
        if value is None:
            return None
        if not isinstance(value, (int, float)):
            return None
        self._metric_call("inc_fault_trigger", tool_name, "low_conf")
        return max(0.0, min(1.0, float(value)))

    def has_active_fault(self, tool_name: str) -> bool:
        self._cleanup_expired()
        for mode in _VALID_MODES:
            if self._effective_value(tool_name, mode) is not None:
                return True
        return False

    async def _expire_later(self, key: tuple[str, str], duration_ms: int) -> None:
        try:
            await asyncio.sleep(max(0, duration_ms) / 1000.0)
            async with self._lock:
                self._rules.pop(key, None)
                self._expiry_tasks.pop(key, None)
            LOGGER.warning("fault_expired tool=%s mode=%s", key[0], key[1])
        except asyncio.CancelledError:
            return

    def _effective_value(self, tool_name: str, mode: str) -> Any:
        self._cleanup_expired()
        direct = self._rules.get((tool_name, mode))
        if direct is not None:
            return direct.value
        fallback = self._rules.get(("all", mode))
        if fallback is not None:
            return fallback.value
        return None

    def _cleanup_expired(self) -> None:
        now_ms = self._now_ms()
        expired_keys = [
            key
            for key, rule in self._rules.items()
            if rule.expires_at_ms is not None and now_ms >= rule.expires_at_ms
        ]
        for key in expired_keys:
            self._rules.pop(key, None)
            task = self._expiry_tasks.pop(key, None)
            if task is not None:
                task.cancel()

    @staticmethod
    def _validate(tool: str, mode: str) -> None:
        if tool not in _VALID_TOOLS:
            raise ValueError(f"unsupported tool: {tool}")
        if mode not in _VALID_MODES:
            raise ValueError(f"unsupported mode: {mode}")

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def _metric_call(self, method: str, *args: Any) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)
