from __future__ import annotations

import asyncio
import contextlib
import csv
import hashlib
import html
import io
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Any, Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ValidationError, model_validator

from byes.config import GatewayConfig, load_config
from byes.confirm_manager import ConfirmManager
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
from byes.preempt_window import PreemptWindow
from byes.runtime_stats import RuntimeStats
from byes.safety import SafetyKernel
from byes.scheduler import Scheduler
from byes.schema import CoordFrame, EventEnvelope, EventType, FrameMeta, HealthStatus, ToolStatus
from byes.tool_registry import ToolRegistry
from byes.tools import MockOcrTool, MockRiskTool, RealDepthTool, RealDetTool, RealOcrTool, RealVlmTool
from byes.tools.base import FrameInput, ToolLane
from byes.world_state import WorldState
from scripts.report_run import generate_report_outputs, load_run_package, safe_extract_zip


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sanitize_file_tag(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return "run"
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "run"


def _slugify_anchor(text: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "").strip().lower())
    normalized = normalized.strip("-")
    return normalized or "section"


def _split_report_sections(report_md: str) -> list[tuple[str, str, str]]:
    lines = (report_md or "").splitlines()
    sections: list[tuple[str, str, str]] = []
    current_title = "Overview"
    current_lines: list[str] = []
    for raw_line in lines:
        line = str(raw_line)
        if line.startswith("## "):
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_title, body, _slugify_anchor(current_title)))
            current_title = line[3:].strip() or "Section"
            current_lines = []
            continue
        current_lines.append(line)
    final_body = "\n".join(current_lines).strip()
    if final_body:
        sections.append((current_title, final_body, _slugify_anchor(current_title)))
    return sections


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
    mode: Literal["timeout", "slow", "low_conf", "disconnect", "critical"]
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


class ConfirmSubmitRequest(BaseModel):
    confirmId: str
    answer: Literal["yes", "no", "unknown"]
    source: str | None = "api"


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
        self.confirm = ConfirmManager(
            metrics=self.metrics,
            default_ttl_ms=self.config.confirm_default_ttl_ms,
            dedup_cooldown_ms=self.config.confirm_dedup_cooldown_ms,
        )
        self.world_state = WorldState(self.config, metrics=self.metrics)
        self.preempt_window = PreemptWindow()
        self.runtime_stats = RuntimeStats(window_size=50, ema_alpha=0.2)
        self.frame_tracker = FrameTracker(
            metrics=self.metrics,
            retention_ms=self.config.frame_tracker_retention_ms,
            max_entries=self.config.frame_tracker_max_entries,
            governor=self.governor,
        )
        self.preprocessor = FramePreprocessor(self.config)
        self.fusion = FusionEngine(
            self.config,
            metrics=self.metrics,
            world_state=self.world_state,
            confirm_manager=self.confirm,
        )
        self.action_gate = ActionPlanGate(metrics=self.metrics)
        if self.config.planner_v1_enabled:
            self.planner = PolicyPlannerV1(
                self.config,
                metrics=self.metrics,
                world_state=self.world_state,
                runtime_stats=self.runtime_stats,
                preempt_window=self.preempt_window,
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
            preempt_window=self.preempt_window,
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
        self.run_packages_root = Path(__file__).resolve().parent / "artifacts" / "run_packages"
        self.run_packages_index_path = self.run_packages_root / "index.json"
        self._run_packages_lock = asyncio.Lock()

    async def startup(self) -> None:
        self.run_packages_root.mkdir(parents=True, exist_ok=True)
        self._external_readiness = {}
        self.registry.clear()
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

    def _to_run_packages_relative(self, path: Path) -> str:
        root = self.run_packages_root.resolve()
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            return str(resolved)
        return relative.as_posix()

    def _resolve_run_packages_path(self, raw_path: str) -> Path:
        candidate = Path(str(raw_path).strip())
        if not candidate.is_absolute():
            candidate = self.run_packages_root / candidate
        resolved = candidate.resolve()
        root = self.run_packages_root.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="path escapes run_packages root") from exc
        return resolved

    def _load_run_packages_index_unlocked(self) -> list[dict[str, Any]]:
        if not self.run_packages_index_path.exists():
            return []
        try:
            payload = json.loads(self.run_packages_index_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(payload, dict):
            items = payload.get("items", [])
        else:
            items = payload
        if not isinstance(items, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            run_id = str(item.get("run_id", "")).strip()
            if not run_id:
                continue
            normalized.append(item)
        normalized.sort(key=lambda row: int(row.get("createdAtMs", 0) or 0), reverse=True)
        return normalized

    def _save_run_packages_index_unlocked(self, entries: list[dict[str, Any]]) -> None:
        self.run_packages_root.mkdir(parents=True, exist_ok=True)
        payload = entries[:200]
        temp_path = self.run_packages_index_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.run_packages_index_path)

    async def register_run_package(self, entry: dict[str, Any]) -> None:
        async with self._run_packages_lock:
            entries = self._load_run_packages_index_unlocked()
            run_id = str(entry.get("run_id", "")).strip()
            entries = [row for row in entries if str(row.get("run_id", "")).strip() != run_id]
            entries.insert(0, entry)
            self._save_run_packages_index_unlocked(entries)

    async def list_run_packages(self, limit: int) -> list[dict[str, Any]]:
        safe_limit = max(1, min(200, int(limit)))
        async with self._run_packages_lock:
            entries = self._load_run_packages_index_unlocked()
            return entries[:safe_limit]

    async def get_run_package(self, run_id: str) -> dict[str, Any] | None:
        lookup = str(run_id or "").strip()
        if not lookup:
            return None
        async with self._run_packages_lock:
            entries = self._load_run_packages_index_unlocked()
            for entry in entries:
                if str(entry.get("run_id", "")).strip() == lookup:
                    return entry
        return None

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
        preempt_active = self.preempt_window.is_active(request_start_ms)
        enriched_meta["preemptWindowActive"] = bool(preempt_active)
        enriched_meta["preemptWindowUntilMs"] = int(self.preempt_window.active_until_ms)
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
        self.preempt_window.reset_runtime()
        self.intent.reset_runtime()
        self.confirm.reset_runtime()
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
            "confirmPending": self.confirm.pending_count,
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
            self.confirm.expire(now_ms)
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
        if lane == ToolLane.FAST:
            frame.meta["_fast_risk_critical"] = False
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
                    if (
                        lane == ToolLane.FAST
                        and event.type == EventType.RISK
                        and str(event.riskLevel.value if event.riskLevel is not None else event.payload.get("riskLevel", "warn")).strip().lower() == "critical"
                    ):
                        frame.meta["_fast_risk_critical"] = True
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
            if event.type == EventType.ACTION_PLAN and bool(event.payload.get("confirmId")):
                self.metrics.inc_confirm_suppressed("safe_mode")
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


@app.get("/api/confirm/pending")
async def confirm_pending(sessionId: str = "default") -> dict[str, Any]:
    now_ms = _now_ms()
    gateway.confirm.expire(now_ms)
    pending = gateway.confirm.get_pending(sessionId)
    if pending is None:
        return {"ok": True, "pending": None}
    return {"ok": True, "pending": pending.model_dump(mode="json")}


@app.post("/api/confirm")
async def confirm_submit(request: ConfirmSubmitRequest) -> dict[str, Any]:
    now_ms = _now_ms()
    gateway.confirm.expire(now_ms)
    resolved = gateway.confirm.resolve(
        request.confirmId,
        request.answer,
        now_ms,
        source=str(request.source or "api"),
    )
    if not resolved:
        return {"ok": False, "resolved": False, "reason": "not_found"}

    pending_req, pending_resp = gateway.confirm.pop_last_resolution()
    if pending_req is not None and pending_resp is not None:
        gateway.world_state.record_confirm_response(
            session_id=pending_req.sessionId,
            kind=pending_req.kind,
            answer=pending_resp.answer,
            now_ms=now_ms,
            confirmed_ttl_ms=gateway.config.confirm_yes_ttl_ms,
            suppress_ttl_ms=gateway.config.confirm_no_suppress_ms,
        )
    return {
        "ok": True,
        "resolved": True,
        "confirmId": request.confirmId,
        "answer": request.answer,
    }


@app.post("/api/run_package/upload")
async def run_package_upload(
    request: Request,
    file: UploadFile = File(...),
    scenarioTag: str | None = Form(default=None),
) -> dict[str, Any]:
    filename = (file.filename or "").strip().lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="file must be .zip")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty zip payload")

    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    scenario = _sanitize_file_tag(scenarioTag)
    artifacts_root = gateway.run_packages_root
    artifacts_root.mkdir(parents=True, exist_ok=True)

    zip_path = artifacts_root / f"{timestamp}_{scenario}.zip"
    run_dir = artifacts_root / f"{timestamp}_{scenario}"

    try:
        zip_path.write_bytes(payload)
        run_dir.mkdir(parents=True, exist_ok=True)
        safe_extract_zip(zip_path, run_dir)

        package_dir = run_dir
        try:
            load_run_package(package_dir)
        except Exception:
            candidates = list(run_dir.rglob("manifest.json")) + list(run_dir.rglob("run_manifest.json"))
            if not candidates:
                raise
            package_dir = candidates[0].parent

        ws_jsonl, metrics_before, metrics_after, run_pkg_summary = load_run_package(package_dir)
        report_md_path = package_dir / "report.md"
        report_json_path = package_dir / "report.json"
        generated_md, generated_json, summary = generate_report_outputs(
            ws_jsonl=ws_jsonl,
            output=report_md_path,
            metrics_url="http://127.0.0.1:8000/metrics",
            metrics_before_path=metrics_before,
            metrics_after_path=metrics_after,
            external_readiness_url=None,
            run_package_summary=run_pkg_summary,
            output_json=report_json_path,
        )

        run_id = package_dir.name
        created_at_ms = _now_ms()
        index_entry = {
            "run_id": run_id,
            "scenarioTag": run_pkg_summary.get("scenarioTag", scenario or "run"),
            "createdAtMs": created_at_ms,
            "zipPath": gateway._to_run_packages_relative(zip_path),  # noqa: SLF001
            "reportMdPath": gateway._to_run_packages_relative(generated_md),  # noqa: SLF001
            "reportJsonPath": gateway._to_run_packages_relative(generated_json or report_json_path),  # noqa: SLF001
            "summary": summary,
        }
        await gateway.register_run_package(index_entry)
        base_url = str(request.base_url).rstrip("/")
        run_url = f"{base_url}/runs/{run_id}"
        summary_url = f"{base_url}/api/run_packages/{run_id}/summary"
        zip_url = f"{base_url}/api/run_packages/{run_id}/zip"

        return {
            "ok": True,
            "runId": run_id,
            "runDir": str(package_dir),
            "reportMdPath": str(generated_md),
            "reportJsonPath": str(generated_json or report_json_path),
            "runUrl": run_url,
            "reportUrl": f"{run_url}#report",
            "summaryUrl": summary_url,
            "zipUrl": zip_url,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"run package processing failed: {ex}") from ex


@app.get("/api/run_packages")
async def run_packages_list(
    request: Request,
    limit: int = 20,
    scenario: str | None = None,
    run_id: str | None = None,
    start_from_ms: int | None = None,
    start_to_ms: int | None = None,
    has_gt: str = "any",
    min_quality: float | None = None,
    sort: str = "createdAtMs",
    order: str = "desc",
) -> dict[str, Any]:
    items = await _query_run_package_rows(
        request,
        limit=limit,
        scenario=scenario,
        run_id=run_id,
        start_from_ms=start_from_ms,
        start_to_ms=start_to_ms,
        has_gt=has_gt,
        min_quality=min_quality,
        sort=sort,
        order=order,
    )
    return {
        "ok": True,
        "items": items,
        "filters": {
            "scenario": scenario or "",
            "run_id": run_id or "",
            "start_from_ms": start_from_ms,
            "start_to_ms": start_to_ms,
            "has_gt": has_gt,
            "min_quality": min_quality,
            "sort": sort,
            "order": order,
            "limit": limit,
        },
    }


@app.get("/api/run_packages/export.json")
async def run_packages_export_json(
    request: Request,
    limit: int = 200,
    scenario: str | None = None,
    run_id: str | None = None,
    start_from_ms: int | None = None,
    start_to_ms: int | None = None,
    has_gt: str = "any",
    min_quality: float | None = None,
    sort: str = "createdAtMs",
    order: str = "desc",
) -> dict[str, Any]:
    items = await _query_run_package_rows(
        request,
        limit=limit,
        scenario=scenario,
        run_id=run_id,
        start_from_ms=start_from_ms,
        start_to_ms=start_to_ms,
        has_gt=has_gt,
        min_quality=min_quality,
        sort=sort,
        order=order,
    )
    return {
        "ok": True,
        "items": items,
    }


@app.get("/api/run_packages/export.csv")
async def run_packages_export_csv(
    request: Request,
    limit: int = 200,
    scenario: str | None = None,
    run_id: str | None = None,
    start_from_ms: int | None = None,
    start_to_ms: int | None = None,
    has_gt: str = "any",
    min_quality: float | None = None,
    sort: str = "createdAtMs",
    order: str = "desc",
) -> Response:
    items = await _query_run_package_rows(
        request,
        limit=limit,
        scenario=scenario,
        run_id=run_id,
        start_from_ms=start_from_ms,
        start_to_ms=start_to_ms,
        has_gt=has_gt,
        min_quality=min_quality,
        sort=sort,
        order=order,
    )

    fields = [
        "runId",
        "scenarioTag",
        "startMs",
        "endMs",
        "frameCountSent",
        "e2e_count",
        "e2e_p50",
        "ttfa_p50",
        "safemode_enter",
        "throttle_enter",
        "preempt_enter",
        "confirm_req",
        "confirm_resp",
        "confirm_timeout",
        "safety_score",
        "quality_has_gt",
        "quality_score",
        "runUrl",
        "reportUrl",
        "summaryUrl",
        "zipUrl",
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in items:
        writer.writerow({key: row.get(key) for key in fields})

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=run_packages.csv"},
    )


def _load_run_summary_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    report_path = gateway._resolve_run_packages_path(str(entry.get("reportJsonPath", "")))  # noqa: SLF001
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="report json not found")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"report json parse failed: {ex}") from ex
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="report json invalid")
    return payload


def _load_run_report_md_from_entry(entry: dict[str, Any]) -> str:
    report_path = gateway._resolve_run_packages_path(str(entry.get("reportMdPath", "")))  # noqa: SLF001
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="report md not found")
    try:
        return report_path.read_text(encoding="utf-8-sig")
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"report md read failed: {ex}") from ex


def _load_run_manifest_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    report_path = gateway._resolve_run_packages_path(str(entry.get("reportMdPath", "")))  # noqa: SLF001
    package_dir = report_path.parent
    candidates = [package_dir / "manifest.json", package_dir / "run_manifest.json"]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _read_float(payload: dict[str, Any], key: str) -> float | None:
    raw = payload.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _extract_p50(summary: dict[str, Any], candidates: list[str]) -> float | None:
    for key in candidates:
        value = _read_float(summary, key)
        if value is not None:
            return value
    return None


def _compute_safety_score(summary: dict[str, Any]) -> float:
    safemode_enter = _read_float(summary, "safemode_enter") or 0.0
    throttle_enter = _read_float(summary, "throttle_enter") or 0.0
    preempt_enter = _read_float(summary, "preempt_enter") or 0.0
    confirm_timeout = _read_float(summary, "confirm_timeout") or 0.0
    confirm_request = _read_float(summary, "confirm_request") or 0.0
    confirm_response = _read_float(summary, "confirm_response") or 0.0
    perception_violation = _read_float(summary, "perception_after_safe_mode") or 0.0
    action_violation = _read_float(summary, "action_plan_after_safe_mode") or 0.0
    missed_confirm = max(0.0, confirm_request - confirm_response)

    score = 100.0
    score -= safemode_enter * 35.0
    score -= throttle_enter * 10.0
    score -= preempt_enter * 8.0
    score -= confirm_timeout * 6.0
    score -= missed_confirm * 2.0
    score -= (perception_violation + action_violation) * 3.0
    if score < 0.0:
        return 0.0
    if score > 100.0:
        return 100.0
    return round(score, 2)


def _build_run_urls(base_url: str, run_id: str) -> dict[str, str]:
    normalized_base = str(base_url or "").rstrip("/")
    run_url = f"{normalized_base}/runs/{run_id}"
    return {
        "runUrl": run_url,
        "reportUrl": f"{run_url}#report",
        "summaryUrl": f"{normalized_base}/api/run_packages/{run_id}/summary",
        "zipUrl": f"{normalized_base}/api/run_packages/{run_id}/zip",
    }


def _build_leaderboard_row(entry: dict[str, Any], base_url: str) -> dict[str, Any] | None:
    run_id = str(entry.get("run_id", "")).strip()
    if not run_id:
        return None
    try:
        summary = _load_run_summary_from_entry(entry)
    except HTTPException:
        return None
    manifest = _load_run_manifest_from_entry(entry)
    urls = _build_run_urls(base_url, run_id)
    created_at_ms = int(entry.get("createdAtMs", 0) or 0)
    frame_count_sent = int(manifest.get("frameCountSent", 0) or 0)
    frame_count_sent = frame_count_sent or int((_read_float(summary, "frame_received") or 0.0))

    quality_payload = summary.get("quality", {})
    has_gt = bool(quality_payload.get("hasGroundTruth")) if isinstance(quality_payload, dict) else False
    quality_score = _read_float(quality_payload, "qualityScore") if isinstance(quality_payload, dict) else None

    row = {
        "run_id": run_id,
        "runId": run_id,
        "scenarioTag": str(entry.get("scenarioTag", "") or manifest.get("scenarioTag", "")),
        "createdAtMs": created_at_ms,
        "startMs": int(manifest.get("startMs", 0) or 0),
        "endMs": int(manifest.get("endMs", 0) or 0),
        "frameCountSent": frame_count_sent,
        "e2e_count": int((_read_float(summary, "e2e_count") or 0.0)),
        "e2e_sum": _read_float(summary, "e2e_sum") or 0.0,
        "e2e_p50": _extract_p50(summary, ["e2e_p50", "e2eP50"]),
        "ttfa_count": int((_read_float(summary, "ttfa_count") or 0.0)),
        "ttfa_sum": _read_float(summary, "ttfa_sum") or 0.0,
        "ttfa_p50": _extract_p50(summary, ["ttfa_p50", "ttfaP50"]),
        "safemode_enter": int((_read_float(summary, "safemode_enter") or 0.0)),
        "throttle_enter": int((_read_float(summary, "throttle_enter") or 0.0)),
        "preempt_enter": int((_read_float(summary, "preempt_enter") or 0.0)),
        "confirm_req": int((_read_float(summary, "confirm_request") or 0.0)),
        "confirm_resp": int((_read_float(summary, "confirm_response") or 0.0)),
        "confirm_timeout": int((_read_float(summary, "confirm_timeout") or 0.0)),
        "safety_score": _compute_safety_score(summary),
        "quality_has_gt": has_gt,
        "quality_score": quality_score,
        "summary": summary,
    }
    row.update(urls)
    return row


def _matches_run_filters(
    row: dict[str, Any],
    *,
    scenario: str | None,
    run_id: str | None,
    start_from_ms: int | None,
    start_to_ms: int | None,
    has_gt: str | None,
    min_quality: float | None,
) -> bool:
    if scenario:
        if scenario.lower() not in str(row.get("scenarioTag", "")).lower():
            return False
    if run_id:
        if run_id.lower() not in str(row.get("runId", "")).lower():
            return False
    if start_from_ms is not None:
        if int(row.get("startMs", 0) or 0) < start_from_ms:
            return False
    if start_to_ms is not None:
        if int(row.get("startMs", 0) or 0) > start_to_ms:
            return False
    if has_gt:
        normalized = has_gt.strip().lower()
        if normalized in {"true", "1", "yes"} and not bool(row.get("quality_has_gt")):
            return False
        if normalized in {"false", "0", "no"} and bool(row.get("quality_has_gt")):
            return False
    if min_quality is not None:
        quality = row.get("quality_score")
        if quality is None:
            return False
        if float(quality) < float(min_quality):
            return False
    return True


def _sort_run_rows(rows: list[dict[str, Any]], sort: str, order: str) -> list[dict[str, Any]]:
    sort_key = str(sort or "createdAtMs")
    allowed = {
        "createdAtMs",
        "startMs",
        "scenarioTag",
        "frameCountSent",
        "e2e_count",
        "ttfa_count",
        "safety_score",
        "quality",
        "quality_score",
        "safemode_enter",
        "throttle_enter",
        "preempt_enter",
    }
    if sort_key not in allowed:
        sort_key = "createdAtMs"
    if sort_key == "quality":
        sort_key = "quality_score"
    reverse = str(order or "desc").lower() != "asc"

    def key_fn(row: dict[str, Any]) -> Any:
        value = row.get(sort_key)
        if value is None:
            if sort_key == "scenarioTag":
                return "" if reverse else "~~~"
            return float("-inf") if reverse else float("inf")
        return value

    return sorted(rows, key=key_fn, reverse=reverse)


async def _query_run_package_rows(
    request: Request,
    *,
    limit: int,
    scenario: str | None,
    run_id: str | None,
    start_from_ms: int | None,
    start_to_ms: int | None,
    has_gt: str | None,
    min_quality: float | None,
    sort: str,
    order: str,
) -> list[dict[str, Any]]:
    base_url = str(request.base_url).rstrip("/")
    entries = await gateway.list_run_packages(200)
    rows: list[dict[str, Any]] = []
    for entry in entries:
        row = _build_leaderboard_row(entry, base_url)
        if row is None:
            continue
        if not _matches_run_filters(
            row,
            scenario=scenario,
            run_id=run_id,
            start_from_ms=start_from_ms,
            start_to_ms=start_to_ms,
            has_gt=has_gt,
            min_quality=min_quality,
        ):
            continue
        rows.append(row)
    rows = _sort_run_rows(rows, sort, order)
    safe_limit = max(1, min(200, int(limit)))
    return rows[:safe_limit]


@app.get("/api/run_packages/{run_id}/summary")
async def run_package_summary(run_id: str) -> dict[str, Any]:
    entry = await gateway.get_run_package(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="run_id not found")
    return _load_run_summary_from_entry(entry)


@app.get("/api/run_packages/{run_id}/report")
async def run_package_report(run_id: str) -> FileResponse:
    entry = await gateway.get_run_package(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="run_id not found")
    report_path = gateway._resolve_run_packages_path(str(entry.get("reportMdPath", "")))  # noqa: SLF001
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="report md not found")
    return FileResponse(path=report_path, media_type="text/markdown", filename=f"{run_id}.md")


@app.get("/api/run_packages/{run_id}/zip")
async def run_package_zip(run_id: str) -> FileResponse:
    entry = await gateway.get_run_package(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="run_id not found")
    zip_path = gateway._resolve_run_packages_path(str(entry.get("zipPath", "")))  # noqa: SLF001
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="zip not found")
    return FileResponse(path=zip_path, media_type="application/zip", filename=f"{run_id}.zip")


@app.get("/runs", response_class=HTMLResponse)
async def runs_dashboard(
    request: Request,
    limit: int = 50,
    scenario: str | None = None,
    run_id: str | None = None,
    has_gt: str = "any",
    min_quality: float | None = None,
    sort: str = "createdAtMs",
    order: str = "desc",
) -> HTMLResponse:
    base_url = str(request.base_url).rstrip("/")
    rows = await _query_run_package_rows(
        request,
        limit=limit,
        scenario=scenario,
        run_id=run_id,
        start_from_ms=None,
        start_to_ms=None,
        has_gt=has_gt,
        min_quality=min_quality,
        sort=sort,
        order=order,
    )
    rows_html = ""
    for row in rows:
        run_val = html.escape(str(row.get("runId", "")))
        tag = html.escape(str(row.get("scenarioTag", "")))
        created = html.escape(str(row.get("createdAtMs", 0)))
        safety = html.escape(f"{float(row.get('safety_score', 0.0)):.2f}")
        quality_raw = row.get("quality_score")
        quality = "—"
        if quality_raw is not None:
            quality = f"{float(quality_raw):.2f}"
        if row.get("quality_has_gt"):
            quality = f"{quality} (GT)" if quality != "—" else "GT"
        rows_html += (
            "<tr>"
            f"<td><input type='checkbox' data-run-id='{run_val}' /></td>"
            f"<td><a href='{base_url}/runs/{run_val}'>{run_val}</a></td>"
            f"<td>{tag}</td>"
            f"<td>{created}</td>"
            f"<td>{safety}</td>"
            f"<td>{html.escape(quality)}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html = "<tr><td colspan='6' class='muted'>no runs</td></tr>"

    scenario_value = html.escape(scenario or "")
    run_id_value = html.escape(run_id or "")
    sort_value = html.escape(sort or "createdAtMs")
    order_value = html.escape(order or "desc")
    limit_value = html.escape(str(limit))
    has_gt_value = html.escape(has_gt or "any")
    min_quality_value = html.escape("" if min_quality is None else str(min_quality))
    html_page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Run Packages</title>
  <style>
    body {{ font-family: monospace; margin: 20px; background: #111; color: #eee; }}
    a {{ color: #7cc7ff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .muted {{ color: #999; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #2b2b2b; padding: 6px; text-align: left; }}
    th {{ color: #bbb; }}
    .panel {{ border: 1px solid #333; padding: 12px; border-radius: 8px; margin-top: 12px; }}
    button {{ margin-right: 8px; }}
  </style>
</head>
<body>
  <h1>Run Packages</h1>
  <div class="muted">Source: <code>{html.escape(base_url)}</code></div>
  <div class="panel">
    <form method="get" action="{base_url}/runs">
      <label>scenario: <input type="text" name="scenario" value="{scenario_value}" /></label>
      <label>run_id: <input type="text" name="run_id" value="{run_id_value}" /></label>
      <label>has_gt:
        <select name="has_gt">
          <option value="any" {"selected" if has_gt_value == "any" else ""}>any</option>
          <option value="true" {"selected" if has_gt_value == "true" else ""}>true</option>
          <option value="false" {"selected" if has_gt_value == "false" else ""}>false</option>
        </select>
      </label>
      <label>min_quality: <input type="number" step="0.01" name="min_quality" value="{min_quality_value}" /></label>
      <label>sort:
        <select name="sort">
          <option value="createdAtMs" {"selected" if sort_value == "createdAtMs" else ""}>createdAtMs</option>
          <option value="safety_score" {"selected" if sort_value == "safety_score" else ""}>safety_score</option>
          <option value="quality" {"selected" if sort_value == "quality" else ""}>quality</option>
          <option value="e2e_count" {"selected" if sort_value == "e2e_count" else ""}>e2e_count</option>
          <option value="ttfa_count" {"selected" if sort_value == "ttfa_count" else ""}>ttfa_count</option>
          <option value="frameCountSent" {"selected" if sort_value == "frameCountSent" else ""}>frameCountSent</option>
        </select>
      </label>
      <label>order:
        <select name="order">
          <option value="desc" {"selected" if order_value == "desc" else ""}>desc</option>
          <option value="asc" {"selected" if order_value == "asc" else ""}>asc</option>
        </select>
      </label>
      <label>limit: <input type="number" name="limit" min="1" max="200" value="{limit_value}" /></label>
      <button type="submit">Apply</button>
      <a href="{base_url}/api/run_packages/export.csv?scenario={scenario_value}&run_id={run_id_value}&has_gt={has_gt_value}&min_quality={min_quality_value}&sort={sort_value}&order={order_value}&limit={limit_value}">Export CSV</a>
      <a href="{base_url}/api/run_packages/export.json?scenario={scenario_value}&run_id={run_id_value}&has_gt={has_gt_value}&min_quality={min_quality_value}&sort={sort_value}&order={order_value}&limit={limit_value}">Export JSON</a>
    </form>
    <button id="compare">Compare Selected (2)</button>
    <table>
      <thead>
        <tr>
          <th>Pick</th>
          <th>Run</th>
          <th>Scenario</th>
          <th>Created</th>
          <th>Safety Score</th>
          <th>Quality</th>
        </tr>
      </thead>
      <tbody id="runs">{rows_html}</tbody>
    </table>
  </div>
  <script>
    const selected = [];
    function toggleSelected(runId, checked) {{
      if (checked) {{
        if (!selected.includes(runId)) {{
          selected.push(runId);
        }}
      }} else {{
        selected = selected.filter(x => x !== runId);
      }}
      if (selected.length > 2) {{
        selected = selected.slice(selected.length - 2);
      }}
      const checks = document.querySelectorAll("input[data-run-id]");
      checks.forEach(cb => {{
        const runIdValue = cb.getAttribute("data-run-id");
        cb.checked = selected.includes(runIdValue);
      }});
    }}
    document.querySelectorAll("input[data-run-id]").forEach(cb => {{
      cb.addEventListener("change", ev => toggleSelected(cb.getAttribute("data-run-id"), ev.target.checked));
    }});
    document.getElementById("compare").addEventListener("click", () => {{
      if (selected.length !== 2) {{
        alert("Select exactly 2 runs to compare.");
        return;
      }}
      const qs = encodeURIComponent(selected[0]) + "," + encodeURIComponent(selected[1]);
      window.location.href = "{base_url}/runs/compare?ids=" + qs;
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_page)


@app.get("/runs/compare", response_class=HTMLResponse)
async def runs_compare_page(ids: str, request: Request) -> HTMLResponse:
    parts = [part.strip() for part in str(ids or "").split(",") if part.strip()]
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="ids must contain exactly 2 run ids separated by comma")
    run_a, run_b = parts[0], parts[1]
    entry_a = await gateway.get_run_package(run_a)
    entry_b = await gateway.get_run_package(run_b)
    if entry_a is None or entry_b is None:
        raise HTTPException(status_code=404, detail="one or more run ids not found")
    summary_a = _load_run_summary_from_entry(entry_a)
    summary_b = _load_run_summary_from_entry(entry_b)
    base_url = str(request.base_url).rstrip("/")

    compare_keys: list[tuple[str, str]] = [
        ("frame_received", "Frame Received"),
        ("frame_completed", "Frame Completed"),
        ("e2e_count", "E2E Count"),
        ("e2e_sum", "E2E Sum"),
        ("ttfa_count", "TTFA Count"),
        ("ttfa_sum", "TTFA Sum"),
        ("safemode_enter", "SafeMode Enter"),
        ("throttle_enter", "Throttle Enter"),
        ("preempt_enter", "Preempt Enter"),
        ("confirm_request", "Confirm Request"),
        ("confirm_response", "Confirm Response"),
    ]
    rows_html = ""
    for key, label in compare_keys:
        value_a = summary_a.get(key, 0)
        value_b = summary_b.get(key, 0)
        rows_html += (
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(str(value_a))}</td>"
            f"<td>{html.escape(str(value_b))}</td>"
            "</tr>"
        )

    html_page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Run Compare</title>
  <style>
    body {{ font-family: monospace; margin: 20px; background: #111; color: #eee; }}
    a {{ color: #7cc7ff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
    th, td {{ border-bottom: 1px solid #2b2b2b; padding: 8px; text-align: left; }}
    th {{ color: #bbb; }}
    .panel {{ border: 1px solid #333; padding: 12px; border-radius: 8px; margin-top: 12px; }}
  </style>
</head>
<body>
  <h1>Run Compare</h1>
  <div><a href="{base_url}/runs">Back to Run Packages</a></div>
  <div class="panel">
    <div>A: <a href="{base_url}/runs/{html.escape(run_a)}">{html.escape(run_a)}</a></div>
    <div>B: <a href="{base_url}/runs/{html.escape(run_b)}">{html.escape(run_b)}</a></div>
  </div>
  <table>
    <thead>
      <tr>
        <th>Metric</th>
        <th>{html.escape(run_a)}</th>
        <th>{html.escape(run_b)}</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</body>
</html>"""
    return HTMLResponse(content=html_page)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_details_page(run_id: str, request: Request) -> HTMLResponse:
    entry = await gateway.get_run_package(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="run_id not found")

    base_url = str(request.base_url).rstrip("/")
    safe_run_id = html.escape(run_id)
    summary_url = f"{base_url}/api/run_packages/{run_id}/summary"
    report_url = f"{base_url}/api/run_packages/{run_id}/report"
    zip_url = f"{base_url}/api/run_packages/{run_id}/zip"
    summary = _load_run_summary_from_entry(entry)
    report_md = _load_run_report_md_from_entry(entry)
    sections = _split_report_sections(report_md)
    nav_links = []
    for title, _body, anchor in sections:
        nav_links.append(f'<a href="#{html.escape(anchor)}">{html.escape(title)}</a>')
    nav_html = " | ".join(nav_links) if nav_links else "<span class=\"muted\">no report sections</span>"

    cards = [
        ("frame", f"{int(summary.get('frame_received', 0))}/{int(summary.get('frame_completed', 0))}"),
        ("e2e", f"count={int(summary.get('e2e_count', 0))}, sum={int(summary.get('e2e_sum', 0))}"),
        ("ttfa", f"count={int(summary.get('ttfa_count', 0))}, sum={int(summary.get('ttfa_sum', 0))}"),
        ("safe", str(int(summary.get("safemode_enter", 0)))),
        ("throttle", str(int(summary.get("throttle_enter", 0)))),
        ("preempt", str(int(summary.get("preempt_enter", 0)))),
        ("confirm", f"req={int(summary.get('confirm_request', 0))}, resp={int(summary.get('confirm_response', 0))}"),
    ]
    cards_html = "".join(
        f"<div class='card'><div class='muted'>{html.escape(k)}</div><div>{html.escape(v)}</div></div>"
        for k, v in cards
    )
    sections_html = ""
    for title, body, anchor in sections:
        sections_html += (
            f"<details open id='{html.escape(anchor)}'>"
            f"<summary>{html.escape(title)}</summary>"
            f"<pre>{html.escape(body)}</pre>"
            f"</details>"
        )
    if not sections_html:
        sections_html = "<div class='muted'>report.md is empty</div>"

    html_page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Run {safe_run_id}</title>
  <style>
    body {{ font-family: monospace; margin: 20px; background: #111; color: #eee; }}
    a {{ color: #7cc7ff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .muted {{ color: #999; }}
    .panel {{ border: 1px solid #333; padding: 12px; border-radius: 8px; margin-top: 12px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }}
    .card {{ border: 1px solid #2b2b2b; border-radius: 8px; padding: 8px; background: #0b0b0b; }}
    summary {{ cursor: pointer; font-weight: bold; }}
    details {{ margin-top: 8px; border: 1px solid #2b2b2b; border-radius: 8px; padding: 6px; background: #0d0d0d; }}
    pre {{ white-space: pre-wrap; background: #0b0b0b; border: 1px solid #2c2c2c; padding: 12px; border-radius: 8px; }}
  </style>
</head>
<body>
  <h1>Run {safe_run_id}</h1>
  <div><a href="{base_url}/runs">Back to Run Packages</a> | <a href="{base_url}/runs/compare?ids={html.escape(run_id)},{html.escape(run_id)}">Compare (replace 2nd id manually)</a></div>
  <div class="panel">
    <div><strong>Summary API:</strong> <a href="{summary_url}">{summary_url}</a></div>
    <div><strong>Report API:</strong> <a href="{report_url}">{report_url}</a></div>
    <div><strong>Zip API:</strong> <a href="{zip_url}">{zip_url}</a></div>
  </div>
  <div class="panel">
    <h3>Summary Cards</h3>
    <div class="cards">{cards_html}</div>
  </div>
  <div class="panel">
    <h3>Report Navigation</h3>
    <div>{nav_html}</div>
  </div>
  <div class="panel" id="report">
    <h3>Report.md Sections</h3>
    {sections_html}
  </div>
</body>
</html>"""
    return HTMLResponse(content=html_page)


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
