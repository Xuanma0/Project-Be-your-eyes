from __future__ import annotations

from dataclasses import dataclass

from byes.config import GatewayConfig
from byes.schema import ActionType, EventEnvelope, EventType, RiskLevel


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

        degraded = bool(self._safe_call(self._degradation, "is_degraded", default=False))
        if degraded and not safe_mode:
            fresh = [self._apply_degraded_guard(event) for event in fresh]

        risk_events = [event for event in fresh if event.type == EventType.RISK]
        if risk_events:
            for risk in risk_events:
                if risk.riskLevel is None:
                    risk.riskLevel = RiskLevel.WARN
                if "riskLevel" not in risk.payload:
                    risk.payload = {**dict(risk.payload), "riskLevel": risk.riskLevel.value}
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

    def _apply_degraded_guard(self, event: EventEnvelope) -> EventEnvelope:
        if event.type == EventType.NAVIGATION:
            payload = dict(event.payload)
            action = str(payload.get("action", ""))
            if action in {ActionType.MOVE.value, ActionType.TURN.value}:
                payload["action"] = ActionType.STOP.value
                payload["fallback"] = ActionType.SCAN.value
                payload["reason"] = "degraded_navigation_downgraded"
                event.payload = payload
            return event

        if event.type != EventType.ACTION_PLAN:
            return event

        payload = dict(event.payload)
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            return event
        steps = plan.get("steps")
        if not isinstance(steps, list):
            return event

        changed = False
        for step in steps:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action", ""))
            if action in {ActionType.MOVE.value, ActionType.TURN.value}:
                step["action"] = ActionType.STOP.value
                step["text"] = "Degraded mode: stop and scan."
                changed = True
        if changed:
            plan["mode"] = "degraded"
            plan["fallback"] = ActionType.SCAN.value
            payload["plan"] = plan
            payload["reason"] = "degraded_actionplan_downgraded"
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
