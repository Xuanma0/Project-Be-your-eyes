from __future__ import annotations

from dataclasses import dataclass

from byes.config import GatewayConfig
from byes.schema import ActionType, EventEnvelope, EventType


@dataclass
class SafetyDecision:
    events: list[EventEnvelope]


class SafetyKernel:
    def __init__(self, config: GatewayConfig, degradation_manager: object | None = None) -> None:
        self._config = config
        self._degradation = degradation_manager

    def adjudicate(self, events: list[EventEnvelope], now_ms: int) -> SafetyDecision:
        if not events:
            return SafetyDecision(events=[])

        fresh = [event for event in events if not event.is_expired(now_ms)]
        if not fresh:
            return SafetyDecision(events=[])

        safe_mode = bool(self._safe_call(self._degradation, "is_safe_mode", default=False))
        if safe_mode:
            fresh = [event for event in fresh if event.type in {EventType.RISK, EventType.HEALTH}]
            if not fresh:
                return SafetyDecision(events=[])

        risk_events = [event for event in fresh if event.type == EventType.RISK]
        if risk_events:
            # Invariant 1: risk preempts every non-risk event.
            risk_events.sort(key=lambda item: item.priority, reverse=True)
            return SafetyDecision(events=risk_events)

        gated = [self._apply_navigation_confidence_guard(event) for event in fresh]
        gated.sort(key=lambda item: item.priority, reverse=True)
        return SafetyDecision(events=gated)

    def _apply_navigation_confidence_guard(self, event: EventEnvelope) -> EventEnvelope:
        if event.type != EventType.NAVIGATION:
            return event

        payload = dict(event.payload)
        action = str(payload.get("action", ""))
        if event.confidence >= self._config.low_confidence_threshold:
            return event

        if action in {ActionType.MOVE.value, ActionType.TURN.value}:
            # Invariant 3: low confidence cannot output pass-through commands.
            payload["action"] = ActionType.STOP.value
            payload["fallback"] = ActionType.SCAN.value
            payload["reason"] = "low_confidence_navigation_blocked"
            event.payload = payload
        return event

    @staticmethod
    def _safe_call(target: object | None, method: str, default: object = None) -> object:
        if target is None:
            return default
        fn = getattr(target, method, None)
        if not callable(fn):
            return default
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return default
