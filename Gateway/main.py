from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
from urllib.parse import urlparse, urlunparse
from typing import Any, Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError, model_validator

from byes.config import GatewayConfig, load_config
from byes.degradation import DegradationManager, DegradationState
from byes.action_gate import ActionPlanGate
from byes.faults import FaultManager
from byes.frame_tracker import FrameTracker
from byes.fusion import FusionEngine
from byes.governor import SloGovernor
from byes.intent import IntentManager
from byes.metrics import GatewayMetrics
from byes.observability import Observability
from byes.planner import PolicyPlannerV0, PolicyPlannerV1
from byes.preprocess import FramePreprocessor
from byes.runtime_stats import RuntimeStats
from byes.safety import SafetyKernel
from byes.scheduler import Scheduler
from byes.schema import CoordFrame, EventEnvelope, EventType, FrameMeta, HealthStatus, ToolStatus
from byes.tool_registry import ToolRegistry
from byes.tools import MockOcrTool, MockRiskTool, RealDepthTool, RealDetTool, RealOcrTool, RealVlmTool
from byes.tools.base import FrameInput, ToolLane
from byes.world_state import WorldState


def _now_ms() -> int:
    return int(time.time() * 1000)


class MockEvent(BaseModel):
    type: str
    timestampMs: int
    coordFrame: str
    confidence: float
    ttlMs: int
    source: str
    riskText: str | None = None
    summary: str | None = None
    distanceM: float | None = None
    azimuthDeg: float | None = None


class FaultSetRequest(BaseModel):
    tool: Literal["mock_risk", "mock_ocr", "real_det", "real_ocr", "real_depth", "real_vlm", "all"]
    mode: Literal["timeout", "slow", "low_conf", "disconnect"]
    value: float | bool | int | None = None
    durationMs: int | None = None


class IntentRequest(BaseModel):
    intent: str | None = None
    kind: str | None = None
    question: str | None = None
    durationMs: int | None = 5000

    @model_validator(mode="after")
    def _normalize(self) -> "IntentRequest":
        resolved = self.kind if self.kind is not None else self.intent
        normalized = str(resolved or "none").strip().lower()
        if normalized == "qa":
            normalized = "ask"
        if normalized not in {"none", "scan_text", "ask"}:
            raise ValueError("kind/intent must be one of: none, scan_text, ask, qa")
        self.kind = normalized
        self.intent = normalized
        if normalized == "ask":
            question = str(self.question or "").strip()
            if not question:
                raise ValueError("ask intent requires non-empty question")
            self.question = question
        else:
            self.question = None
        return self


class CrossCheckRequest(BaseModel):
    kind: Literal["none", "vision_without_depth", "depth_without_vision"] = "none"
    durationMs: int | None = 10000


class PerformanceRequest(BaseModel):
    mode: Literal["normal", "throttled"] = "normal"
    reason: str | None = "manual_override"
    durationMs: int | None = 10000


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.active.discard(ws)

    async def broadcast_json(self, obj: dict[str, Any]) -> None:
        failed: list[WebSocket] = []
        async with self._lock:
            targets = list(self.active)

        for ws in targets:
            try:
                await ws.send_json(obj)
            except Exception:  # noqa: BLE001
                failed.append(ws)

        if failed:
            async with self._lock:
                for ws in failed:
                    self.active.discard(ws)

    async def count(self) -> int:
        async with self._lock:
            return len(self.active)


class GatewayApp:
    SAFE_MODE_HEALTH_SUMMARY = (
        "System unstable. Safe mode active: risk alerts only. Please stop and scan surroundings."
    )

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.config: GatewayConfig = load_config()
        self.metrics = GatewayMetrics()
        self.observability = Observability("be-your-eyes-gateway")
        self.registry = ToolRegistry()
        self.degradation = DegradationManager(self.config, self.metrics)
        self.governor = SloGovernor(self.config, metrics=self.metrics)
        self.faults = FaultManager(self.metrics)
        self.intent = IntentManager()
        self.world_state = WorldState(self.config)
        self.runtime_stats = RuntimeStats(window_size=50, ema_alpha=0.2)
        self.frame_tracker = FrameTracker(
            metrics=self.metrics,
            retention_ms=self.config.frame_tracker_retention_ms,
            max_entries=self.config.frame_tracker_max_entries,
            governor=self.governor,
        )
        self.preprocessor = FramePreprocessor(self.config)
        self.fusion = FusionEngine(self.config, metrics=self.metrics, world_state=self.world_state)
        self.action_gate = ActionPlanGate(metrics=self.metrics)
        if self.config.planner_v1_enabled:
            self.planner = PolicyPlannerV1(
                self.config,
                metrics=self.metrics,
                world_state=self.world_state,
                runtime_stats=self.runtime_stats,
            )
        else:
            self.planner = PolicyPlannerV0(self.config)
        self.safety = SafetyKernel(self.config, self.degradation)
        self.connections = ConnectionManager()
        self.scheduler = Scheduler(
            config=self.config,
            registry=self.registry,
            on_lane_results=self._on_lane_results,
            metrics=self.metrics,
            degradation_manager=self.degradation,
            observability=self.observability,
            fault_manager=self.faults,
            on_frame_terminal=self._on_frame_terminal,
            planner=self.planner,
            frame_tracker=self.frame_tracker,
            preprocessor=self.preprocessor,
            world_state=self.world_state,
            runtime_stats=self.runtime_stats,
        )
        self._mock_flip = False
        self._degrade_watchdog_task: asyncio.Task[None] | None = None
        self._last_safe_mode_pulse_ms = -1
        self._safe_mode_pulse_interval_ms = 1000
        self._last_meta_warn_ms: dict[str, int] = {"meta_missing": -1, "meta_parse_error": -1}
        self._enabled_tools = self._parse_csv_tools(self.config.enabled_tools_csv)
        self._external_readiness: dict[str, dict[str, Any]] = {}
        self._forced_crosscheck_kind = "none"
        self._forced_crosscheck_expires_ms = -1
        self._forced_performance_mode = "NORMAL"
        self._forced_performance_reason = "manual_override"
        self._forced_performance_expires_ms = -1

    async def startup(self) -> None:
        self._external_readiness = {}
        startup_unavailable_tools: list[str] = []
        if self._tool_enabled("mock_risk"):
            self.registry.register(MockRiskTool(self.config))
        if self._tool_enabled("mock_ocr"):
            self.registry.register(MockOcrTool(self.config))

        real_tools: list[tuple[str, str, Any]] = []
        if self.config.enable_real_det and self._tool_enabled("real_det"):
            real_tools.append(("real_det", self.config.real_det_endpoint, RealDetTool))
        if self.config.enable_real_ocr and self._tool_enabled("real_ocr"):
            real_tools.append(("real_ocr", self.config.real_ocr_endpoint, RealOcrTool))
        if self.config.enable_real_depth and self._tool_enabled("real_depth"):
            real_tools.append(("real_depth", self.config.real_depth_endpoint, RealDepthTool))
        if self.config.real_vlm_url.strip() and self._tool_enabled("real_vlm"):
            real_tools.append(("real_vlm", self.config.real_vlm_url, RealVlmTool))

        for tool_name, endpoint, factory in real_tools:
            readiness = await self._probe_external_service(tool_name, endpoint)
            self._external_readiness[tool_name] = readiness
            if bool(readiness.get("ready", False)):
                self.registry.register(factory(self.config))
            else:
                startup_unavailable_tools.append(tool_name)

        registered_tools = {item.name for item in self.registry.list_descriptors()}
        self.degradation.set_tool_inventory(registered_tools, self._enabled_tools or None)
        for tool_name in startup_unavailable_tools:
            self.metrics.inc_tool_skipped(tool_name, "unavailable")
            self.degradation.record_unavailable(tool_name)
        self.observability.instrument_app(self.app)
        await self.scheduler.start()
        self.degradation.set_ws_client_count(0)
        self._degrade_watchdog_task = asyncio.create_task(self._degradation_watchdog_loop())

    async def shutdown(self) -> None:
        if self._degrade_watchdog_task is not None:
            self._degrade_watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._degrade_watchdog_task
            self._degrade_watchdog_task = None

        await self.scheduler.stop()
        await self.faults.shutdown()

    async def submit_frame(
        self,
        frame_bytes: bytes,
        meta: dict[str, Any],
        request: Request,
        frame_meta: FrameMeta | None = None,
    ) -> int:
        request_start_ms = _now_ms()
        trace = self.observability.extract_trace(request.headers)
        enriched_meta = dict(meta)
        enriched_meta["traceId"] = trace.trace_id
        enriched_meta["spanId"] = trace.span_id
        active_intent = self.intent.active_intent()
        enriched_meta["intent"] = active_intent
        active_question = self.intent.active_question()
        if active_intent == "ask" and active_question:
            enriched_meta["intentQuestion"] = active_question
        governor_snapshot = self.governor.snapshot()
        effective_mode, effective_reason = self._effective_performance(governor_snapshot.mode, governor_snapshot.reason)
        if "performanceMode" not in enriched_meta:
            enriched_meta["performanceMode"] = effective_mode
        if "performanceReason" not in enriched_meta:
            enriched_meta["performanceReason"] = effective_reason
        forced_crosscheck_kind = self._active_forced_crosscheck_kind()
        if forced_crosscheck_kind != "none" and "forceCrosscheckKind" not in enriched_meta:
            enriched_meta["forceCrosscheckKind"] = forced_crosscheck_kind
        enriched_meta["fingerprint"] = hashlib.sha1(frame_bytes).hexdigest()

        seq = await self.scheduler.submit_frame(
            frame_bytes=frame_bytes,
            meta=enriched_meta,
            trace_id=trace.trace_id,
            span_id=trace.span_id,
        )
        ttl_ms = int(enriched_meta.get("ttlMs", self.config.default_ttl_ms))
        if ttl_ms <= 0:
            ttl_ms = self.config.default_ttl_ms
        self.frame_tracker.start_frame(seq, request_start_ms, ttl_ms, frame_meta=frame_meta)
        return seq

    async def reset_runtime(self) -> dict[str, Any]:
        faults_snapshot = await self.faults.clear_faults()
        self.degradation.reset_runtime()
        self.frame_tracker.reset_runtime()
        self.governor.reset_runtime()
        self.intent.reset_runtime()
        self.world_state.reset_runtime()
        self.runtime_stats.reset_runtime()
        self.fusion.reset_runtime()
        self.scheduler.reset_runtime()
        self._last_safe_mode_pulse_ms = -1
        self._last_meta_warn_ms = {"meta_missing": -1, "meta_parse_error": -1}
        self._forced_crosscheck_kind = "none"
        self._forced_crosscheck_expires_ms = -1
        self._forced_performance_mode = "NORMAL"
        self._forced_performance_reason = "manual_override"
        self._forced_performance_expires_ms = -1
        client_count = await self.connections.count()
        self.degradation.set_ws_client_count(client_count)
        return {
            "state": self.degradation.state.value,
            "clients": client_count,
            "hadClientEverConnected": self.degradation.had_client_ever_connected,
            "frameTrackerRecords": self.frame_tracker.record_count,
            "intent": self.intent.active_intent(),
            "intentQuestion": self.intent.active_question(),
            "performanceMode": self.governor.mode,
            "performanceReason": self.governor.reason,
            "forcedCrosscheckKind": self._forced_crosscheck_kind,
            "forcedPerformanceMode": self._forced_performance_mode,
            "faults": faults_snapshot.get("faults", []),
        }

    def _on_frame_terminal(self, frame: FrameInput, outcome: str) -> None:
        self.frame_tracker.complete_frame(frame.seq, outcome, _now_ms())

    def parse_optional_frame_meta(self, raw_meta: str | None) -> tuple[dict[str, Any], FrameMeta | None, str]:
        if raw_meta is None or not raw_meta.strip():
            return {}, None, "missing"

        try:
            payload = json.loads(raw_meta)
        except json.JSONDecodeError:
            return {}, None, "parse_error"

        if not isinstance(payload, dict):
            return {}, None, "parse_error"

        meta_payload = dict(payload)
        frame_meta_candidate = meta_payload.get("frameMeta", meta_payload)
        if frame_meta_candidate is None:
            return meta_payload, None, "missing"
        if not isinstance(frame_meta_candidate, dict):
            return meta_payload, None, "parse_error"

        try:
            frame_meta = FrameMeta.model_validate(frame_meta_candidate)
        except ValidationError:
            return meta_payload, None, "parse_error"

        if frame_meta.is_empty():
            return meta_payload, None, "missing"

        meta_payload["frameMeta"] = frame_meta.model_dump(mode="json", exclude_none=True)
        if frame_meta.deviceTsMs is not None and "tsCaptureMs" not in meta_payload:
            meta_payload["tsCaptureMs"] = int(frame_meta.deviceTsMs)
        if frame_meta.frameSeq is not None and "clientSeq" not in meta_payload:
            meta_payload["clientSeq"] = int(frame_meta.frameSeq)
        if frame_meta.coordFrame is not None and "coordFrame" not in meta_payload:
            meta_payload["coordFrame"] = frame_meta.coordFrame.value
        return meta_payload, frame_meta, "present"

    @staticmethod
    def _parse_csv_tools(raw_csv: str) -> set[str]:
        return {item.strip().lower() for item in str(raw_csv).split(",") if item.strip()}

    def _tool_enabled(self, tool_name: str) -> bool:
        if not self._enabled_tools:
            return True
        return tool_name.strip().lower() in self._enabled_tools

    @staticmethod
    def _healthz_url_from_endpoint(endpoint: str) -> str:
        parsed = urlparse(str(endpoint).strip())
        if not parsed.scheme or not parsed.netloc:
            return ""
        return urlunparse((parsed.scheme, parsed.netloc, "/healthz", "", "", ""))

    async def _probe_external_service(self, tool_name: str, endpoint: str) -> dict[str, Any]:
        healthz_url = self._healthz_url_from_endpoint(endpoint)
        snapshot: dict[str, Any] = {
            "tool": tool_name,
            "endpoint": endpoint,
            "healthz": healthz_url,
            "ready": False,
            "reason": "probe_failed",
        }
        if not healthz_url:
            snapshot["reason"] = "invalid_endpoint"
            return snapshot

        try:
            timeout_s = max(0.2, self.config.default_ttl_ms / 3000.0)
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.get(healthz_url)
            snapshot["httpStatus"] = int(response.status_code)
            if response.status_code >= 400:
                snapshot["reason"] = f"http_{response.status_code}"
                return snapshot
            payload = response.json()
            if not isinstance(payload, dict):
                snapshot["reason"] = "invalid_payload"
                return snapshot
            ready = bool(payload.get("ready", False))
            warmed_up = bool(payload.get("warmed_up", False))
            if ready and warmed_up:
                snapshot["ready"] = True
                snapshot["reason"] = "ok"
            else:
                snapshot["reason"] = "not_ready"
            snapshot["backend"] = str(payload.get("backend", ""))
            snapshot["model_id"] = str(payload.get("model_id", ""))
            snapshot["version"] = str(payload.get("version", ""))
            snapshot["warmed_up"] = warmed_up
            return snapshot
        except Exception as exc:  # noqa: BLE001
            snapshot["reason"] = f"probe_error:{exc.__class__.__name__}"
            return snapshot

    def _active_forced_crosscheck_kind(self) -> str:
        now_ms = _now_ms()
        if self._forced_crosscheck_expires_ms > 0 and now_ms >= self._forced_crosscheck_expires_ms:
            self._forced_crosscheck_kind = "none"
            self._forced_crosscheck_expires_ms = -1
        return self._forced_crosscheck_kind

    def set_forced_crosscheck(self, kind: str, duration_ms: int) -> dict[str, Any]:
        normalized = str(kind or "none").strip()
        if normalized not in {"none", "vision_without_depth", "depth_without_vision"}:
            raise ValueError("kind must be one of: none, vision_without_depth, depth_without_vision")
        if normalized == "none":
            self._forced_crosscheck_kind = "none"
            self._forced_crosscheck_expires_ms = -1
            return {"kind": self._forced_crosscheck_kind, "expiresAtMs": self._forced_crosscheck_expires_ms}
        now_ms = _now_ms()
        ttl_ms = max(1, int(duration_ms))
        self._forced_crosscheck_kind = normalized
        self._forced_crosscheck_expires_ms = now_ms + ttl_ms
        return {"kind": self._forced_crosscheck_kind, "expiresAtMs": self._forced_crosscheck_expires_ms}

    def _effective_performance(self, governor_mode: str, governor_reason: str) -> tuple[str, str]:
        now_ms = _now_ms()
        if self._forced_performance_expires_ms > 0 and now_ms >= self._forced_performance_expires_ms:
            self._forced_performance_mode = "NORMAL"
            self._forced_performance_reason = "manual_override_expired"
            self._forced_performance_expires_ms = -1
        if self._forced_performance_expires_ms > 0:
            return self._forced_performance_mode, self._forced_performance_reason
        return governor_mode, governor_reason

    def set_forced_performance(self, mode: str, reason: str, duration_ms: int) -> dict[str, Any]:
        normalized = str(mode or "normal").strip().upper()
        if normalized not in {"NORMAL", "THROTTLED"}:
            raise ValueError("mode must be one of: normal, throttled")
        if normalized == "NORMAL":
            self._forced_performance_mode = "NORMAL"
            self._forced_performance_reason = "manual_override"
            self._forced_performance_expires_ms = -1
            return {
                "mode": self._forced_performance_mode,
                "reason": self._forced_performance_reason,
                "expiresAtMs": self._forced_performance_expires_ms,
            }
        now_ms = _now_ms()
        ttl_ms = max(1, int(duration_ms))
        normalized_reason = str(reason or "manual_override").strip() or "manual_override"
        self._forced_performance_mode = normalized
        self._forced_performance_reason = normalized_reason
        self._forced_performance_expires_ms = now_ms + ttl_ms
        return {
            "mode": self._forced_performance_mode,
            "reason": self._forced_performance_reason,
            "expiresAtMs": self._forced_performance_expires_ms,
        }

    @staticmethod
    def _format_health_summary(health_status: HealthStatus, reason: str) -> str:
        return f"gateway_{health_status.value.lower()} ({reason})"

    async def _emit_health_event(
        self,
        *,
        seq: int,
        ts_capture_ms: int,
        ttl_ms: int,
        trace_id: str,
        span_id: str,
        health_status: HealthStatus,
        health_reason: str,
        source: str,
        level: str = "info",
    ) -> None:
        summary = self._format_health_summary(health_status, health_reason)
        await self._emit_event(
            EventEnvelope(
                type=EventType.HEALTH,
                traceId=trace_id,
                spanId=span_id,
                seq=seq,
                tsCaptureMs=ts_capture_ms,
                ttlMs=ttl_ms,
                coordFrame=CoordFrame.WORLD,
                confidence=1.0,
                priority=self.config.health_priority,
                source=source,
                healthStatus=health_status,
                healthReason=health_reason,
                payload={
                    "status": summary.split(" ", 1)[0],
                    "reason": health_reason,
                    "summary": summary,
                    "level": level,
                    "healthStatus": health_status.value,
                    "healthReason": health_reason,
                },
            )
        )

    async def emit_meta_health_warn(self, status: str, reason: str, min_interval_ms: int = 5000) -> None:
        now_ms = _now_ms()
        last_ms = self._last_meta_warn_ms.get(status, -1)
        if last_ms >= 0 and now_ms - last_ms < min_interval_ms:
            return
        self._last_meta_warn_ms[status] = now_ms

        health_status = HealthStatus.WAITING_CLIENT if status == "meta_missing" else HealthStatus.DEGRADED
        await self._emit_health_event(
            seq=0,
            ts_capture_ms=now_ms,
            ttl_ms=self.config.default_ttl_ms,
            trace_id="0" * 32,
            span_id="0" * 16,
            health_status=health_status,
            health_reason=reason,
            source="frame_meta@v1.3",
            level="warn",
        )

    async def emit_degradation_changes(
        self,
        seq: int,
        ts_capture_ms: int,
        ttl_ms: int,
        trace_id: str,
        span_id: str,
    ) -> None:
        for change in self.degradation.consume_state_changes():
            if change.current == DegradationState.SAFE_MODE:
                health_status = HealthStatus.SAFE_MODE
            elif change.current == DegradationState.DEGRADED:
                health_status = HealthStatus.DEGRADED
            else:
                health_status = HealthStatus.NORMAL
            await self._emit_health_event(
                seq=seq,
                ts_capture_ms=ts_capture_ms,
                ttl_ms=ttl_ms,
                trace_id=trace_id,
                span_id=span_id,
                health_status=health_status,
                health_reason=change.reason,
                source="degradation@v1.3.1",
            )

        for alert in self.degradation.consume_alerts():
            health_status = HealthStatus.WAITING_CLIENT if alert.reason == "waiting_client" else HealthStatus.DEGRADED
            await self._emit_health_event(
                seq=seq,
                ts_capture_ms=ts_capture_ms,
                ttl_ms=ttl_ms,
                trace_id=trace_id,
                span_id=span_id,
                health_status=health_status,
                health_reason=alert.reason,
                source="degradation@v1.3.1",
                level="warn",
            )

    async def _degradation_watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            now_ms = _now_ms()
            self.degradation.tick()
            queue_depth = self.scheduler.queue_depth_snapshot()
            max_depth = max(queue_depth.values()) if queue_depth else 0
            timeout_rate = self.degradation.timeout_rate()
            governor_snapshot = self.governor.tick(
                queue_depth=max_depth,
                timeout_rate=timeout_rate,
            )
            effective_mode, effective_reason = self._effective_performance(
                governor_snapshot.mode,
                governor_snapshot.reason,
            )
            await self.emit_degradation_changes(
                seq=0,
                ts_capture_ms=now_ms,
                ttl_ms=self.config.default_ttl_ms,
                trace_id="0" * 32,
                span_id="0" * 16,
            )
            health_status_raw, health_reason = self.degradation.get_health()
            try:
                health_status = HealthStatus(health_status_raw)
            except ValueError:
                health_status = HealthStatus.DEGRADED
            if health_status in {HealthStatus.NORMAL, HealthStatus.WAITING_CLIENT} and effective_mode == "THROTTLED":
                health_status = HealthStatus.THROTTLED
                health_reason = effective_reason or "slo_pressure"
            if not health_reason:
                health_reason = "tool_result:normal" if health_status == HealthStatus.NORMAL else "waiting_client"
            await self._emit_health_event(
                seq=0,
                ts_capture_ms=now_ms,
                ttl_ms=self.config.default_ttl_ms,
                trace_id="0" * 32,
                span_id="0" * 16,
                health_status=health_status,
                health_reason=health_reason,
                source="degradation@v1.3.1",
            )

    async def _on_lane_results(self, frame: FrameInput, lane: ToolLane, results: list[Any]) -> None:
        trace_id = str(frame.meta.get("traceId", "0" * 32))
        span_id = str(frame.meta.get("spanId", "0" * 16))
        _reported_status, health_reason = self.degradation.get_health()
        health_status = self.degradation.state.value
        fused = self.fusion.fuse_lane(
            frame=frame,
            lane=lane,
            results=results,
            trace_id=trace_id,
            span_id=span_id,
            health_status=health_status,
        )
        self._record_crosscheck_metrics(fused.diagnostics)

        emitted_count = 0
        for stage_events in (fused.stage1_events, fused.stage2_events):
            if not stage_events:
                continue
            now = _now_ms()
            gated, blocked = self.action_gate.gate_events_with_diagnostics(
                stage_events,
                health_status=health_status,
                health_reason=health_reason,
            )
            for seq, reason, kind in blocked:
                self.frame_tracker.note_ttfa_block(seq, f"action_gate:{reason}", kind)
            decision = self.safety.adjudicate(gated, now_ms=now)
            for event in decision.events:
                if event.is_expired(now):
                    self.metrics.inc_deadline_miss(lane.value)
                    continue
                if await self._emit_event(event):
                    emitted_count += 1

        now = _now_ms()
        if emitted_count > 0:
            self.frame_tracker.complete_frame(frame.seq, "ok", now)
        elif lane == ToolLane.FAST:
            # No final event from fast lane.
            # - Safe mode: suppression is expected.
            # - Normal/degraded with at least one OK tool result: treat as handled (e.g., hazard dedup).
            # - Otherwise keep error for full tool failures/timeouts.
            has_ok_result = any(getattr(item, "status", None) == ToolStatus.OK for item in results)
            if self.degradation.is_safe_mode():
                outcome = "safemode_suppressed"
            elif has_ok_result:
                outcome = "ok"
            else:
                outcome = "error"
            self.frame_tracker.complete_frame(frame.seq, outcome, now)

        await self.emit_degradation_changes(
            seq=frame.seq,
            ts_capture_ms=frame.ts_capture_ms,
            ttl_ms=frame.ttl_ms,
            trace_id=trace_id,
            span_id=span_id,
        )

    def _record_crosscheck_metrics(self, diagnostics: list[dict[str, object]]) -> None:
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "")).strip()
            if kind:
                self.metrics.inc_crosscheck_conflict(kind)
            if bool(item.get("activeConfirm", False)) and kind:
                self.metrics.inc_active_confirm(kind)
            if bool(item.get("patched", False)):
                self.metrics.inc_actionplan_patched("crosscheck")

    async def _emit_event(self, event: EventEnvelope) -> bool:
        if self.degradation.is_safe_mode() and event.type in {EventType.PERCEPTION, EventType.ACTION_PLAN}:
            tool_name = str(event.source).split("@", 1)[0] if event.source else "unknown"
            self.metrics.inc_tool_skipped(tool_name, "safe_mode")
            blocked_kind = "action_plan" if event.type == EventType.ACTION_PLAN else "none"
            self.frame_tracker.note_ttfa_block(event.seq, "safe_mode", blocked_kind)
            return False
        if self.config.send_envelope:
            await self.connections.broadcast_json(event.model_dump(mode="json"))
        else:
            await self.connections.broadcast_json(self.fusion.to_legacy_event(event))

        if event.seq > 0 and event.type in {EventType.RISK, EventType.ACTION_PLAN}:
            ttfa_kind = "risk" if event.type == EventType.RISK else "action_plan"
            self.frame_tracker.mark_first_action(event.seq, _now_ms(), ttfa_kind)
        return True

    def build_mock_event(self) -> MockEvent:
        self._mock_flip = not self._mock_flip
        now_ms = _now_ms()
        if self._mock_flip:
            return MockEvent(
                type="risk",
                timestampMs=now_ms,
                coordFrame="World",
                confidence=0.9,
                ttlMs=3000,
                source="gateway",
                riskText="Obstacle ahead",
                distanceM=1.5,
                azimuthDeg=0.0,
            )
        return MockEvent(
            type="perception",
            timestampMs=now_ms,
            coordFrame="World",
            confidence=0.9,
            ttlMs=3000,
            source="gateway",
            summary="Door detected",
        )


app = FastAPI(title="BeYourEyes Gateway")
gateway = GatewayApp(app)


@app.on_event("startup")
async def _startup() -> None:
    await gateway.startup()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await gateway.shutdown()


@app.get("/api/health")
def health() -> dict[str, Any]:
    health_status, health_reason = gateway.degradation.get_health()
    governor_snapshot = gateway.governor.snapshot()
    effective_mode, effective_reason = gateway._effective_performance(  # noqa: SLF001
        governor_snapshot.mode,
        governor_snapshot.reason,
    )
    if health_status in {"NORMAL", "WAITING_CLIENT"} and effective_mode == "THROTTLED":
        health_status = "THROTTLED"
        health_reason = effective_reason
    return {
        "ok": True,
        "ts": _now_ms(),
        "state": gateway.degradation.state.value,
        "healthStatus": health_status,
        "healthReason": health_reason,
        "performanceMode": effective_mode,
        "performanceReason": effective_reason,
        "clients": len(gateway.connections.active),
        "hadClientEverConnected": gateway.degradation.had_client_ever_connected,
        "intent": gateway.intent.active_intent(),
        "intentQuestion": gateway.intent.active_question(),
        "forcedCrosscheckKind": gateway._active_forced_crosscheck_kind(),  # noqa: SLF001
        "forcedPerformanceMode": gateway._forced_performance_mode,  # noqa: SLF001
        "forcedPerformanceExpiresAtMs": gateway._forced_performance_expires_ms,  # noqa: SLF001
        "faults": gateway.faults.snapshot().get("faults", []),
    }


@app.get("/api/mock_event", response_model=MockEvent)
def mock_event() -> MockEvent:
    return gateway.build_mock_event()


@app.get("/api/tools")
def list_tools() -> dict[str, Any]:
    return {"tools": [item.__dict__ for item in gateway.registry.list_descriptors()]}


@app.get("/api/external_readiness")
def external_readiness() -> dict[str, Any]:
    return {"tools": gateway._external_readiness}  # noqa: SLF001


@app.post("/api/frame")
async def frame(
    request: Request,
    image: UploadFile | None = File(default=None),
    meta: str | None = Form(None),
) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type", "")).lower()
    frame_bytes: bytes | None = None
    raw_meta: str | None = None

    if "multipart/form-data" in content_type:
        if image is None:
            raise HTTPException(status_code=400, detail="image is required")
        frame_bytes = await image.read()
        raw_meta = meta
    elif content_type.startswith("image/") or "application/octet-stream" in content_type:
        frame_bytes = await request.body()
    else:
        if image is not None:
            frame_bytes = await image.read()
            raw_meta = meta
        else:
            frame_bytes = await request.body()

    if frame_bytes is None or len(frame_bytes) == 0:
        raise HTTPException(status_code=400, detail="image is empty")

    meta_json, frame_meta, meta_state = gateway.parse_optional_frame_meta(raw_meta)
    if meta_state == "present":
        gateway.metrics.inc_frame_meta_present()
    elif meta_state == "parse_error":
        gateway.metrics.inc_frame_meta_parse_error()
        await gateway.emit_meta_health_warn("meta_parse_error", "frame_meta_invalid_json_or_schema")
    else:
        gateway.metrics.inc_frame_meta_missing()
        await gateway.emit_meta_health_warn("meta_missing", "frame_meta_not_provided")

    seq = await gateway.submit_frame(frame_bytes=frame_bytes, meta=meta_json, request=request, frame_meta=frame_meta)
    return {"ok": True, "bytes": len(frame_bytes), "seq": seq}


@app.post("/api/fault/set")
async def fault_set(request: FaultSetRequest) -> dict[str, Any]:
    try:
        snapshot = await gateway.faults.set_fault(
            tool=request.tool,
            mode=request.mode,
            value=request.value,
            duration_ms=request.durationMs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **snapshot}


@app.post("/api/fault/clear")
async def fault_clear() -> dict[str, Any]:
    snapshot = await gateway.faults.clear_faults()
    return {"ok": True, **snapshot}


@app.post("/api/dev/reset")
async def dev_reset() -> dict[str, Any]:
    runtime = await gateway.reset_runtime()
    return {"ok": True, **runtime}


@app.post("/api/dev/intent")
async def dev_intent(request: IntentRequest) -> dict[str, Any]:
    duration_ms = int(request.durationMs or 0)
    try:
        snapshot = gateway.intent.set_intent(request.kind or "none", duration_ms, question=request.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "intent": snapshot.intent,
        "kind": snapshot.intent,
        "question": snapshot.question,
        "expiresAtMs": snapshot.expires_at_ms,
    }


@app.post("/api/dev/crosscheck")
async def dev_crosscheck(request: CrossCheckRequest) -> dict[str, Any]:
    duration_ms = int(request.durationMs or 0)
    try:
        snapshot = gateway.set_forced_crosscheck(request.kind, duration_ms)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **snapshot}


@app.post("/api/dev/performance")
async def dev_performance(request: PerformanceRequest) -> dict[str, Any]:
    duration_ms = int(request.durationMs or 0)
    try:
        snapshot = gateway.set_forced_performance(request.mode, request.reason or "manual_override", duration_ms)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **snapshot}


@app.get("/metrics")
def metrics() -> Response:
    rendered = gateway.metrics.render()
    return Response(content=rendered.content, media_type=rendered.content_type)


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await gateway.connections.connect(websocket)
    gateway.degradation.set_ws_client_count(await gateway.connections.count())
    await gateway.emit_degradation_changes(
        seq=0,
        ts_capture_ms=_now_ms(),
        ttl_ms=gateway.config.default_ttl_ms,
        trace_id="0" * 32,
        span_id="0" * 16,
    )

    try:
        while True:
            message = await websocket.receive_text()
            if message == "__ping__":
                await websocket.send_text("__pong__")
    except WebSocketDisconnect:
        pass
    finally:
        await gateway.connections.disconnect(websocket)
        gateway.degradation.set_ws_client_count(await gateway.connections.count())
        await gateway.emit_degradation_changes(
            seq=0,
            ts_capture_ms=_now_ms(),
            ttl_ms=gateway.config.default_ttl_ms,
            trace_id="0" * 32,
            span_id="0" * 16,
        )
