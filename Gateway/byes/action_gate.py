from __future__ import annotations

from dataclasses import dataclass

from byes.schema import EventEnvelope, EventType


@dataclass(frozen=True)
class _RiskSnapshot:
    has_critical: bool
    kind: str | None


@dataclass(frozen=True)
class ActionGateResult:
    allowed: bool
    event: EventEnvelope | None
    reason: str
    patched: bool = False


class ActionPlanGate:
    """Hard safety gate for action-plan events before final emission."""

    def __init__(self, metrics: object | None = None) -> None:
        self._metrics = metrics
        self._critical_kinds = {"dropoff", "vehicle", "obstacle", "obstacle_near"}

    def gate_events(
        self,
        events: list[EventEnvelope],
        *,
        health_status: str,
        health_reason: str,
    ) -> list[EventEnvelope]:
        filtered, _ = self.gate_events_with_diagnostics(
            events,
            health_status=health_status,
            health_reason=health_reason,
        )
        return filtered

    def gate_events_with_diagnostics(
        self,
        events: list[EventEnvelope],
        *,
        health_status: str,
        health_reason: str,
    ) -> tuple[list[EventEnvelope], list[tuple[int, str, str]]]:
        risk_snapshot = self._build_risk_snapshot(events)
        output: list[EventEnvelope] = []
        blocked: list[tuple[int, str, str]] = []
        for event in events:
            result = self._gate_action_plan(
                event,
                health_status=health_status,
                health_reason=health_reason,
                risk_snapshot=risk_snapshot,
            )
            if not result.allowed:
                self._metric_call("inc_actiongate_block", result.reason)
                blocked.append((event.seq, result.reason, "action_plan"))
                continue
            if result.patched:
                self._metric_call("inc_actiongate_patch", result.reason)
            if result.event is not None:
                output.append(result.event)
        return output, blocked

    def _gate_action_plan(
        self,
        event: EventEnvelope,
        *,
        health_status: str,
        health_reason: str,
        risk_snapshot: _RiskSnapshot,
    ) -> ActionGateResult:
        if event.type != EventType.ACTION_PLAN:
            return ActionGateResult(allowed=True, event=event, reason="pass")

        normalized_status = str(health_status).strip().upper()
        if normalized_status == "SAFE_MODE":
            return ActionGateResult(allowed=False, event=None, reason="safe_mode")

        payload = dict(event.payload)
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            return ActionGateResult(allowed=True, event=event, reason="pass")

        steps_raw = plan.get("steps")
        if not isinstance(steps_raw, list):
            return ActionGateResult(allowed=True, event=event, reason="pass")

        reason = "normal_patch"
        if normalized_status == "DEGRADED":
            reason = "degraded_patch"
        elif risk_snapshot.has_critical:
            reason = "critical_risk_patch"

        patched_steps: list[dict[str, object]] = []
        patched = False
        blocked_actions = {"move", "turn"}
        for step in steps_raw:
            if not isinstance(step, dict):
                patched_steps.append({"action": "confirm", "text": "Confirm surroundings."})
                patched = True
                continue
            item = dict(step)
            action = str(item.get("action", "")).strip().lower()
            if action in blocked_actions:
                item["action"] = "stop"
                item["text"] = "Safety gate: stop and scan before moving."
                patched = True
            patched_steps.append(item)

        if not patched:
            return ActionGateResult(allowed=True, event=event, reason="pass")

        # Ensure conservative fallback guidance is available after patching.
        if not any(str(item.get("action", "")).strip().lower() == "scan" for item in patched_steps):
            patched_steps.append({"action": "scan", "text": "Scan surroundings carefully."})
        if not any(str(item.get("action", "")).strip().lower() == "confirm" for item in patched_steps):
            patched_steps.append({"action": "confirm", "text": "Confirm path is clear."})

        plan["steps"] = patched_steps
        plan["mode"] = "safety_guard"
        plan["fallback"] = "scan"
        payload["plan"] = plan
        payload["reason"] = reason
        payload["gateReason"] = reason
        if risk_snapshot.kind is not None:
            payload["gateRiskKind"] = risk_snapshot.kind
        if health_reason:
            payload["gateHealthReason"] = health_reason

        patched_event = event.model_copy(deep=True)
        patched_event.payload = payload
        return ActionGateResult(allowed=True, event=patched_event, reason=reason, patched=True)

    def _build_risk_snapshot(self, events: list[EventEnvelope]) -> _RiskSnapshot:
        for event in events:
            if event.type != EventType.RISK:
                continue
            payload = event.payload if isinstance(event.payload, dict) else {}
            hazard_kind = str(payload.get("hazardKind", payload.get("kind", ""))).strip().lower() or None
            distance = payload.get("distanceM")
            try:
                near = float(distance) <= 1.5
            except (TypeError, ValueError):
                near = False
            if hazard_kind in self._critical_kinds or near:
                return _RiskSnapshot(has_critical=True, kind=hazard_kind)
        return _RiskSnapshot(has_critical=False, kind=None)

    def _metric_call(self, method: str, *args: object) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)
