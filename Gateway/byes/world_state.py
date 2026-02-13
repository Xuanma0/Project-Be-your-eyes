from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from byes.config import GatewayConfig
from byes.schema import ToolResult, ToolStatus


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_session_id(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized or "default"


@dataclass
class _Evidence:
    payload: dict[str, Any]
    timestamp_ms: int
    confidence: float


@dataclass
class _SessionWorldState:
    last_det: _Evidence | None = None
    last_depth_hazards: _Evidence | None = None
    last_ocr: _Evidence | None = None
    last_vlm_answer: _Evidence | None = None
    active_hazards: list[dict[str, Any]] = field(default_factory=list)
    active_hazards_ts_ms: int = -1
    last_updated_ms: int = -1
    crosscheck_kind: str | None = None
    crosscheck_force_tool: str | None = None
    crosscheck_force_expires_ms: int = -1
    crosscheck_last_trigger_ms: dict[str, int] = field(default_factory=dict)
    ask_guidance_last_emit_ms: int = -1
    critical_until_ms: int = -1
    critical_reason: str | None = None
    critical_last_set_ms: int = -1
    confirm_last_response_ms: int = -1
    confirm_last_kind: str | None = None
    confirm_last_answer: str | None = None
    confirm_confirmed_until_by_kind: dict[str, int] = field(default_factory=dict)
    confirm_suppressed_until_by_kind: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldStateSnapshot:
    session_id: str
    last_det: dict[str, Any] | None
    last_depth_hazards: dict[str, Any] | None
    last_ocr: dict[str, Any] | None
    last_vlm_answer: dict[str, Any] | None
    active_hazards: list[dict[str, Any]]
    crosscheck_kind: str | None
    crosscheck_force_tool: str | None
    crosscheck_force_expires_ms: int
    critical_until_ms: int
    critical_reason: str | None
    critical_last_set_ms: int
    confirm_confirmed_kinds: list[str]
    confirm_suppressed_kinds: list[str]

    def has_forced_tool(self, now_ms: int) -> bool:
        return bool(self.crosscheck_force_tool) and self.crosscheck_force_expires_ms > now_ms

    def is_critical_active(self, now_ms: int) -> bool:
        return self.critical_until_ms > now_ms


class WorldState:
    """Session-level short-term world model with bounded memory."""

    _CROSSCHECK_TO_TOOL = {
        "vision_without_depth": "real_depth",
        "depth_without_vision": "real_det",
    }
    _CRITICAL_REASON_TOKENS = {
        "crosscheck",
        "depth_near",
        "hazard_persist",
        "dev_inject",
        "confirmed_hazard",
    }

    def __init__(self, config: GatewayConfig, metrics: object | None = None) -> None:
        self._config = config
        self._metrics = metrics
        self._retention_ms = max(5000, int(config.world_state_retention_ms))
        self._max_sessions = max(1, int(config.world_state_max_sessions))
        self._det_stale_ms = max(100, int(config.planner_det_stale_ms))
        self._depth_stale_ms = max(100, int(config.planner_depth_stale_ms))
        self._ocr_stale_ms = max(100, int(config.planner_ocr_stale_ms))
        self._vlm_stale_ms = max(100, int(config.planner_vlm_stale_ms))
        self._crosscheck_force_ms = max(100, int(config.planner_crosscheck_force_ms))
        self._crosscheck_cooldown_ms = max(0, int(config.planner_crosscheck_cooldown_ms))
        self._ask_guidance_cooldown_ms = max(0, int(config.planner_ask_guidance_cooldown_ms))
        self._critical_latch_ms = max(1, int(config.critical_latch_ms))
        self._text_aliases = {
            item.strip().lower()
            for item in str(config.planner_text_object_aliases_csv).split(",")
            if item.strip()
        }
        self._sessions: dict[str, _SessionWorldState] = {}

    def reset_runtime(self) -> None:
        self._sessions.clear()
        self._set_critical_gauge()

    def set_critical(
        self,
        now_ms: int,
        duration_ms: int,
        reason: str,
        *,
        session_id: str = "default",
    ) -> None:
        current_ms = int(now_ms)
        session = self._session(session_id, current_ms)
        normalized_reason = self._normalize_critical_reason(reason)
        was_active = session.critical_until_ms > current_ms
        session.critical_reason = normalized_reason
        session.critical_last_set_ms = current_ms
        duration = max(1, int(duration_ms)) if int(duration_ms) > 0 else self._critical_latch_ms
        next_until_ms = current_ms + duration
        if next_until_ms > session.critical_until_ms:
            session.critical_until_ms = next_until_ms
        session.last_updated_ms = current_ms
        if not was_active:
            self._metric_call("inc_critical_latch_enter", normalized_reason)
        self._set_critical_gauge(current_ms)

    def is_critical_active(self, now_ms: int, *, session_id: str = "default") -> bool:
        current_ms = int(now_ms)
        session = self._sessions.get(_safe_session_id(session_id))
        if session is None:
            self._set_critical_gauge(current_ms)
            return False
        if session.critical_until_ms > current_ms:
            self._set_critical_gauge(current_ms)
            return True
        if session.critical_until_ms >= 0:
            session.critical_until_ms = -1
            session.critical_reason = None
        self._set_critical_gauge(current_ms)
        return False

    def get_critical_reason(self, now_ms: int, *, session_id: str = "default") -> str | None:
        if not self.is_critical_active(now_ms, session_id=session_id):
            return None
        session = self._sessions.get(_safe_session_id(session_id))
        if session is None:
            return None
        return session.critical_reason

    def ingest_tool_results(
        self,
        *,
        session_id: str,
        results: list[ToolResult],
        now_ms: int | None = None,
        frame_meta: dict[str, Any] | None = None,
    ) -> None:
        current_ms = int(now_ms) if now_ms is not None else _now_ms()
        session = self._session(session_id, current_ms)
        for result in results:
            if result.status != ToolStatus.OK:
                continue
            payload = result.payload if isinstance(result.payload, dict) else {}
            confidence = max(0.0, min(1.0, float(result.confidence)))
            if isinstance(payload.get("detections"), list):
                session.last_det = _Evidence(payload=dict(payload), timestamp_ms=current_ms, confidence=confidence)
            if isinstance(payload.get("hazards"), list):
                session.last_depth_hazards = _Evidence(payload=dict(payload), timestamp_ms=current_ms, confidence=confidence)
            if isinstance(payload.get("lines"), list) or isinstance(payload.get("text"), str):
                session.last_ocr = _Evidence(payload=dict(payload), timestamp_ms=current_ms, confidence=confidence)
            if result.toolName == "real_vlm" or isinstance(payload.get("answerText"), str):
                vlm_payload = dict(payload)
                if frame_meta is not None and "intentQuestion" in frame_meta and "questionHash" not in vlm_payload:
                    question = str(frame_meta.get("intentQuestion") or "").strip().lower()
                    if question:
                        vlm_payload["questionHash"] = str(hash(question))
                session.last_vlm_answer = _Evidence(payload=vlm_payload, timestamp_ms=current_ms, confidence=confidence)
        session.last_updated_ms = current_ms
        self._compact(current_ms)

    def update_active_hazards(
        self,
        *,
        session_id: str,
        hazards: list[dict[str, Any]],
        now_ms: int | None = None,
    ) -> None:
        current_ms = int(now_ms) if now_ms is not None else _now_ms()
        session = self._session(session_id, current_ms)
        session.active_hazards = [dict(item) for item in hazards if isinstance(item, dict)]
        session.active_hazards_ts_ms = current_ms
        session.last_updated_ms = current_ms
        self._compact(current_ms)

    def note_crosscheck_conflict(
        self,
        *,
        session_id: str,
        kind: str,
        now_ms: int | None = None,
    ) -> None:
        current_ms = int(now_ms) if now_ms is not None else _now_ms()
        tool_name = self._CROSSCHECK_TO_TOOL.get(str(kind).strip())
        if not tool_name:
            return
        session = self._session(session_id, current_ms)
        last_ms = session.crosscheck_last_trigger_ms.get(kind, -1)
        if last_ms >= 0 and (current_ms - last_ms) < self._crosscheck_cooldown_ms:
            return
        session.crosscheck_last_trigger_ms[kind] = current_ms
        session.crosscheck_kind = kind
        session.crosscheck_force_tool = tool_name
        session.crosscheck_force_expires_ms = current_ms + self._crosscheck_force_ms
        session.last_updated_ms = current_ms
        self._compact(current_ms)

    def record_confirm_response(
        self,
        *,
        session_id: str,
        kind: str,
        answer: str,
        now_ms: int,
        confirmed_ttl_ms: int = 5000,
        suppress_ttl_ms: int = 8000,
    ) -> None:
        current_ms = int(now_ms)
        normalized_kind = str(kind or "").strip().lower()
        normalized_answer = str(answer or "").strip().lower()
        if not normalized_kind:
            return
        session = self._session(session_id, current_ms)
        session.confirm_last_response_ms = current_ms
        session.confirm_last_kind = normalized_kind
        session.confirm_last_answer = normalized_answer
        if normalized_answer == "yes":
            session.confirm_confirmed_until_by_kind[normalized_kind] = current_ms + max(500, int(confirmed_ttl_ms))
            session.confirm_suppressed_until_by_kind.pop(normalized_kind, None)
            self.set_critical(
                current_ms,
                self._critical_latch_ms,
                "confirmed_hazard",
                session_id=session_id,
            )
        elif normalized_answer in {"no", "unknown"}:
            session.confirm_suppressed_until_by_kind[normalized_kind] = current_ms + max(500, int(suppress_ttl_ms))
            session.confirm_confirmed_until_by_kind.pop(normalized_kind, None)
        session.last_updated_ms = current_ms
        self._purge_confirm_maps(session, current_ms)
        self._compact(current_ms)

    def is_confirm_suppressed(
        self,
        *,
        session_id: str,
        kind: str,
        now_ms: int | None = None,
    ) -> bool:
        current_ms = int(now_ms) if now_ms is not None else _now_ms()
        session = self._sessions.get(_safe_session_id(session_id))
        if session is None:
            return False
        self._purge_confirm_maps(session, current_ms)
        normalized_kind = str(kind or "").strip().lower()
        if not normalized_kind:
            return False
        return session.confirm_suppressed_until_by_kind.get(normalized_kind, -1) > current_ms

    def is_confirmed_hazard(
        self,
        *,
        session_id: str,
        kind: str,
        now_ms: int | None = None,
    ) -> bool:
        current_ms = int(now_ms) if now_ms is not None else _now_ms()
        session = self._sessions.get(_safe_session_id(session_id))
        if session is None:
            return False
        self._purge_confirm_maps(session, current_ms)
        normalized_kind = str(kind or "").strip().lower()
        if not normalized_kind:
            return False
        return session.confirm_confirmed_until_by_kind.get(normalized_kind, -1) > current_ms

    def peek_forced_tool(
        self,
        *,
        session_id: str,
        now_ms: int | None = None,
    ) -> tuple[str | None, str | None]:
        current_ms = int(now_ms) if now_ms is not None else _now_ms()
        snapshot = self.snapshot(session_id=session_id, now_ms=current_ms)
        if snapshot.has_forced_tool(current_ms):
            return snapshot.crosscheck_force_tool, snapshot.crosscheck_kind
        return None, None

    def consume_forced_tool(
        self,
        *,
        session_id: str,
        tool_name: str,
        now_ms: int | None = None,
    ) -> None:
        current_ms = int(now_ms) if now_ms is not None else _now_ms()
        session = self._sessions.get(_safe_session_id(session_id))
        if session is None:
            return
        if session.crosscheck_force_tool != tool_name:
            return
        session.crosscheck_force_tool = None
        session.crosscheck_kind = None
        session.crosscheck_force_expires_ms = -1
        session.last_updated_ms = current_ms

    def need_det(
        self,
        *,
        session_id: str,
        now_ms: int,
        intent: str,
        performance_mode: str,
    ) -> bool:
        forced, _ = self.peek_forced_tool(session_id=session_id, now_ms=now_ms)
        if forced == "real_det":
            return True
        snapshot = self.snapshot(session_id=session_id, now_ms=now_ms)
        stale_ms = self._det_stale_ms
        if str(performance_mode).upper() == "THROTTLED" and str(intent).lower() == "none":
            stale_ms *= 2
        if snapshot.last_det is None:
            return True
        age_ms = now_ms - int(snapshot.last_det.get("timestampMs", -1))
        if age_ms >= stale_ms:
            return True
        if snapshot.last_depth_hazards and not snapshot.last_det:
            return True
        return False

    def need_depth(
        self,
        *,
        session_id: str,
        now_ms: int,
        intent: str,
        performance_mode: str,
    ) -> bool:
        _ = intent
        forced, _kind = self.peek_forced_tool(session_id=session_id, now_ms=now_ms)
        if forced == "real_depth":
            return True
        snapshot = self.snapshot(session_id=session_id, now_ms=now_ms)
        stale_ms = self._depth_stale_ms
        if str(performance_mode).upper() == "THROTTLED":
            stale_ms = int(stale_ms * 1.5)
        if snapshot.last_depth_hazards is None:
            return True
        age_ms = now_ms - int(snapshot.last_depth_hazards.get("timestampMs", -1))
        return age_ms >= stale_ms

    def need_ocr(
        self,
        *,
        session_id: str,
        now_ms: int,
        intent: str,
        performance_mode: str,
    ) -> bool:
        normalized_intent = str(intent).lower()
        if normalized_intent == "scan_text":
            return True

        if str(performance_mode).upper() == "THROTTLED":
            return False
        snapshot = self.snapshot(session_id=session_id, now_ms=now_ms)
        det_payload = snapshot.last_det or {}
        detections = det_payload.get("objects")
        if not isinstance(detections, list):
            detections = []
        has_text_like = any(
            any(alias in str(item.get("class", "")).lower() for alias in self._text_aliases)
            for item in detections
            if isinstance(item, dict)
        )
        if not has_text_like:
            return False
        if snapshot.last_ocr is None:
            return True
        age_ms = now_ms - int(snapshot.last_ocr.get("timestampMs", -1))
        return age_ms >= self._ocr_stale_ms

    def need_vlm(
        self,
        *,
        session_id: str,
        now_ms: int,
        intent: str,
        performance_mode: str,
        question: str,
    ) -> bool:
        if str(intent).lower() not in {"ask", "qa"}:
            return False
        if str(performance_mode).upper() == "THROTTLED":
            return False
        snapshot = self.snapshot(session_id=session_id, now_ms=now_ms)
        question_hash = str(hash(str(question or "").strip().lower()))
        if snapshot.last_vlm_answer is None:
            return True
        last_hash = str(snapshot.last_vlm_answer.get("questionHash", ""))
        if question_hash and question_hash != last_hash:
            return True
        age_ms = now_ms - int(snapshot.last_vlm_answer.get("timestampMs", -1))
        return age_ms >= self._vlm_stale_ms

    def should_emit_ask_guidance(self, *, session_id: str, now_ms: int) -> bool:
        session = self._session(session_id, now_ms)
        if session.ask_guidance_last_emit_ms < 0:
            session.ask_guidance_last_emit_ms = now_ms
            return True
        if (now_ms - session.ask_guidance_last_emit_ms) >= self._ask_guidance_cooldown_ms:
            session.ask_guidance_last_emit_ms = now_ms
            return True
        return False

    def snapshot(self, *, session_id: str, now_ms: int | None = None) -> WorldStateSnapshot:
        current_ms = int(now_ms) if now_ms is not None else _now_ms()
        sid = _safe_session_id(session_id)
        session = self._sessions.get(sid)
        if session is None:
            return WorldStateSnapshot(
                session_id=sid,
                last_det=None,
                last_depth_hazards=None,
                last_ocr=None,
                last_vlm_answer=None,
                active_hazards=[],
                crosscheck_kind=None,
                crosscheck_force_tool=None,
                crosscheck_force_expires_ms=-1,
                critical_until_ms=-1,
                critical_reason=None,
                critical_last_set_ms=-1,
                confirm_confirmed_kinds=[],
                confirm_suppressed_kinds=[],
            )
        self._purge_confirm_maps(session, current_ms)
        return WorldStateSnapshot(
            session_id=sid,
            last_det=_evidence_to_dict(session.last_det),
            last_depth_hazards=_evidence_to_dict(session.last_depth_hazards),
            last_ocr=_evidence_to_dict(session.last_ocr),
            last_vlm_answer=_evidence_to_dict(session.last_vlm_answer),
            active_hazards=[dict(item) for item in session.active_hazards],
            crosscheck_kind=session.crosscheck_kind,
            crosscheck_force_tool=session.crosscheck_force_tool,
            crosscheck_force_expires_ms=session.crosscheck_force_expires_ms,
            critical_until_ms=session.critical_until_ms,
            critical_reason=session.critical_reason,
            critical_last_set_ms=session.critical_last_set_ms,
            confirm_confirmed_kinds=sorted(
                [key for key, until_ms in session.confirm_confirmed_until_by_kind.items() if until_ms > current_ms]
            ),
            confirm_suppressed_kinds=sorted(
                [key for key, until_ms in session.confirm_suppressed_until_by_kind.items() if until_ms > current_ms]
            ),
        )

    def _session(self, session_id: str, now_ms: int) -> _SessionWorldState:
        sid = _safe_session_id(session_id)
        session = self._sessions.get(sid)
        if session is None:
            session = _SessionWorldState(last_updated_ms=now_ms)
            self._sessions[sid] = session
        return session

    def _compact(self, now_ms: int) -> None:
        stale_sessions = [
            key
            for key, state in self._sessions.items()
            if state.last_updated_ms > 0 and (now_ms - state.last_updated_ms) > self._retention_ms
        ]
        for key in stale_sessions:
            self._sessions.pop(key, None)

        if len(self._sessions) <= self._max_sessions:
            return
        ordered = sorted(self._sessions.items(), key=lambda item: item[1].last_updated_ms)
        while len(ordered) > self._max_sessions:
            session_id, _state = ordered.pop(0)
            self._sessions.pop(session_id, None)

        self._set_critical_gauge(now_ms)

    def _set_critical_gauge(self, now_ms: int | None = None) -> None:
        current_ms = int(now_ms) if now_ms is not None else _now_ms()
        active = 0
        for session in self._sessions.values():
            if session.critical_until_ms > current_ms:
                active = 1
                break
        self._metric_call("set_critical_latch_active", active)

    def _normalize_critical_reason(self, reason: str) -> str:
        token = str(reason or "").strip().lower().replace("-", "_")
        if token in self._CRITICAL_REASON_TOKENS:
            return token
        return "crosscheck"

    @staticmethod
    def _purge_confirm_maps(session: _SessionWorldState, now_ms: int) -> None:
        stale_confirmed = [key for key, until_ms in session.confirm_confirmed_until_by_kind.items() if until_ms <= now_ms]
        for key in stale_confirmed:
            session.confirm_confirmed_until_by_kind.pop(key, None)
        stale_suppressed = [key for key, until_ms in session.confirm_suppressed_until_by_kind.items() if until_ms <= now_ms]
        for key in stale_suppressed:
            session.confirm_suppressed_until_by_kind.pop(key, None)

    def _metric_call(self, method: str, *args: Any) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)


def _evidence_to_dict(value: _Evidence | None) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = dict(value.payload)
    if "objects" not in payload and isinstance(payload.get("detections"), list):
        payload["objects"] = [dict(item) for item in payload.get("detections", []) if isinstance(item, dict)]
    payload["timestampMs"] = int(value.timestamp_ms)
    payload["confidence"] = float(value.confidence)
    return payload
