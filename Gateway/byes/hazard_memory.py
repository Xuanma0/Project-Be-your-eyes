from __future__ import annotations

import math
import time
from dataclasses import dataclass

from byes.config import GatewayConfig
from byes.schema import EventEnvelope, EventType


@dataclass
class _HazardRecord:
    hazard_id: str
    kind: str
    first_seen_ms: int
    last_seen_ms: int
    last_emitted_ms: int
    confidence: float
    distance_m: float | None
    azimuth_deg: float | None
    source: str
    summary: str


class HazardMemory:
    def __init__(self, config: GatewayConfig, metrics: object | None = None) -> None:
        self._config = config
        self._metrics = metrics
        self._grace_ms = max(0, int(config.hazard_memory_grace_ms))
        self._emit_cooldown_ms = max(0, int(config.hazard_memory_emit_cooldown_ms))
        self._critical_dist_m = max(0.0, float(config.hazard_memory_critical_dist_m))
        self._max_active = max(1, int(config.hazard_memory_max_active))
        self._decay_ms = max(self._grace_ms + 1, int(config.hazard_memory_decay_ms))
        self._active_by_session: dict[str, dict[str, _HazardRecord]] = {}

    def reset_runtime(self) -> None:
        self._active_by_session.clear()
        self._set_active_gauge()

    def update_and_filter(
        self,
        *,
        session_id: str,
        risks: list[EventEnvelope],
        now_ms: int | None = None,
    ) -> list[EventEnvelope]:
        current_ms = int(now_ms) if now_ms is not None else int(time.time() * 1000)
        sid = session_id.strip() if session_id else "default"
        session = self._active_by_session.setdefault(sid, {})
        self._cleanup_stale(session, current_ms)

        filtered: list[EventEnvelope] = []
        seen_ids: set[str] = set()
        for risk in risks:
            if risk.type != EventType.RISK:
                filtered.append(risk)
                continue

            hazard_kind = self._derive_hazard_kind(risk)
            hazard_id = self._make_hazard_id(risk, hazard_kind)
            if hazard_id in seen_ids:
                self._metric_call("inc_hazard_suppressed", "duplicate")
                continue
            seen_ids.add(hazard_id)

            confidence = max(0.0, min(1.0, float(risk.confidence)))
            distance = self._float_or_none(risk.payload.get("distanceM"))
            azimuth = self._float_or_none(risk.payload.get("azimuthDeg"))
            summary = str(risk.payload.get("summary") or risk.payload.get("riskText") or "hazard")
            source = str(risk.source or "unknown")

            record = session.get(hazard_id)
            previous_seen_ms = -1
            if record is None:
                self._ensure_capacity(session)
                record = _HazardRecord(
                    hazard_id=hazard_id,
                    kind=hazard_kind,
                    first_seen_ms=current_ms,
                    last_seen_ms=current_ms,
                    last_emitted_ms=-1,
                    confidence=confidence,
                    distance_m=distance,
                    azimuth_deg=azimuth,
                    source=source,
                    summary=summary,
                )
                session[hazard_id] = record
                hazard_state = "new"
            else:
                previous_seen_ms = record.last_seen_ms
                record.last_seen_ms = current_ms
                record.confidence = confidence
                record.distance_m = distance
                record.azimuth_deg = azimuth
                record.source = source
                record.summary = summary
                if previous_seen_ms >= 0 and (current_ms - previous_seen_ms) > self._grace_ms:
                    hazard_state = "persisted"
                else:
                    hazard_state = "active"

            is_critical = self._is_critical(hazard_kind, distance)
            cooldown_active = (
                record.last_emitted_ms >= 0 and (current_ms - record.last_emitted_ms) < self._emit_cooldown_ms
            )
            if cooldown_active and not is_critical:
                self._metric_call("inc_hazard_suppressed", "cooldown")
                continue

            risk.payload["hazardId"] = hazard_id
            risk.payload["hazardKind"] = hazard_kind
            risk.payload["hazardState"] = hazard_state
            record.last_emitted_ms = current_ms
            filtered.append(risk)
            self._metric_call("inc_hazard_emit", hazard_kind)

        self._handle_grace_persistence(session, seen_ids, current_ms)
        self._set_active_gauge()
        return filtered

    def _cleanup_stale(self, session: dict[str, _HazardRecord], now_ms: int) -> None:
        stale_ids = [
            hazard_id
            for hazard_id, record in session.items()
            if (now_ms - record.last_seen_ms) > self._decay_ms
        ]
        for hazard_id in stale_ids:
            session.pop(hazard_id, None)
            self._metric_call("inc_hazard_suppressed", "stale")

    def _handle_grace_persistence(self, session: dict[str, _HazardRecord], seen_ids: set[str], now_ms: int) -> None:
        for hazard_id, record in session.items():
            if hazard_id in seen_ids:
                continue
            if (now_ms - record.last_seen_ms) <= self._grace_ms:
                self._metric_call("inc_hazard_persist", record.kind)

    def _ensure_capacity(self, session: dict[str, _HazardRecord]) -> None:
        if len(session) < self._max_active:
            return
        # Evict oldest/lowest confidence first.
        candidate = min(
            session.values(),
            key=lambda item: (item.last_seen_ms, item.confidence),
        )
        session.pop(candidate.hazard_id, None)
        self._metric_call("inc_hazard_suppressed", "capacity")

    def _set_active_gauge(self) -> None:
        total = sum(len(items) for items in self._active_by_session.values())
        self._metric_call("set_hazard_active", total)

    def _derive_hazard_kind(self, risk: EventEnvelope) -> str:
        payload = risk.payload
        raw = str(payload.get("hazardKind") or payload.get("kind") or "").strip().lower()
        if raw:
            return raw
        summary = str(payload.get("summary") or payload.get("riskText") or "").lower()
        if "drop" in summary or "pit" in summary:
            return "dropoff"
        if "transparent" in summary or "glass" in summary:
            return "transparent"
        if "obstacle" in summary:
            return "obstacle"
        return "unknown"

    def _make_hazard_id(self, risk: EventEnvelope, kind: str) -> str:
        payload = risk.payload
        distance = self._float_or_none(payload.get("distanceM"))
        azimuth = self._float_or_none(payload.get("azimuthDeg"))
        q_dist = self._quantize(distance, 0.5)
        q_azimuth = self._quantize(azimuth, 10.0)
        source = str(risk.source or "unknown").split("@", 1)[0]
        return f"{kind}|d{q_dist}|a{q_azimuth}|s{source}"

    def _is_critical(self, kind: str, distance_m: float | None) -> bool:
        if kind == "dropoff":
            return True
        if distance_m is None:
            return False
        return distance_m <= self._critical_dist_m

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(number) or math.isinf(number):
            return None
        return number

    @staticmethod
    def _quantize(value: float | None, step: float) -> str:
        if value is None:
            return "na"
        if step <= 0:
            return f"{value:.2f}"
        bucket = round(value / step) * step
        return f"{bucket:.2f}"

    def _metric_call(self, method: str, *args: object) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)
