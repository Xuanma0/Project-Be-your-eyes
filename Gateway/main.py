from __future__ import annotations

import asyncio
import contextlib
import csv
import hashlib
import html
import io
import json
import os
import re
import shutil
import threading
import tempfile
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
from byes.inference.event_emitters import emit_ocr_events, emit_risk_events, emit_seg_events, emit_depth_events, emit_slam_pose_events
from byes.inference.registry import get_ocr_backend, get_risk_backend, get_seg_backend, get_depth_backend, get_slam_backend
from byes.inference.backends.base import OCRResult, RiskResult, SegResult, DepthResult, SlamResult
from byes.inference.prompt_budget import normalize_prompt, pack_prompt
from byes.inference.seg_context import DEFAULT_SEG_CONTEXT_BUDGET, build_seg_context_from_events
from byes.inference.slam_context import DEFAULT_SLAM_CONTEXT_BUDGET, build_slam_context_pack
from byes.inference.plan_context_pack import (
    DEFAULT_PLAN_CONTEXT_PACK_BUDGET,
    build_plan_context_pack,
    resolve_plan_context_pack_budget_from_env,
)
from byes.mapping.costmap import (
    DEFAULT_COSTMAP_CONFIG,
    DEFAULT_COSTMAP_CONTEXT_BUDGET,
    DEFAULT_COSTMAP_CONTEXT_SOURCE,
    build_costmap_context_pack,
    build_local_costmap,
)
from byes.mapping.costmap_fuser import (
    DEFAULT_COSTMAP_FUSED_CONFIG,
    CostmapFuser,
)
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
from byes.pov.store import PovStore
from byes.pov_context import build_context_pack, finalize_context_pack_text, render_context_text
from byes.plan_context_alignment import compute_plan_context_alignment
from byes.plan_pipeline import extract_risk_summary, generate_action_plan, load_events_v1_rows
from byes.plan_executor import execute_plan as execute_action_plan
from byes.schemas.pov_ir_schema import validate_pov_ir
from byes.model_manifest import build_model_manifest
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


def _contracts_dir() -> Path:
    return Path(__file__).resolve().parent / "contracts"


def _load_contract_lock() -> tuple[Path, dict[str, Any]]:
    lock_path = _contracts_dir() / "contract.lock.json"
    if not lock_path.exists():
        raise FileNotFoundError(f"contract lock not found: {lock_path}")
    payload = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"contract lock must be object: {lock_path}")
    versions = payload.get("versions")
    if not isinstance(versions, dict):
        raise ValueError(f"contract lock missing versions object: {lock_path}")
    return lock_path, payload


def _runtime_contract_defaults() -> dict[str, Any]:
    runtime_cfg = load_config()
    pov_budget = PovContextBudgetRequest().model_dump()
    plan_budget = PlanBudgetRequest().model_dump()
    plan_constraints = PlanConstraintsRequest().model_dump()
    risk_threshold_defaults = {
        "version": "heuristic-risk-v4.29-defaults",
        "depthObsWarn": 1.0,
        "depthObsCrit": 0.55,
        "depthDropoffDelta": 0.4,
        "obsWarn": 0.14,
        "obsCrit": 0.28,
        "dropoffPeak": 28.0,
        "dropoffContrast": 0.2,
        "guardrailDropoffDelta": None,
        "guardrailObstacleP10Crit": None,
    }
    planner_defaults = {
        "backend": str(os.getenv("BYES_PLANNER_BACKEND", "mock")).strip() or "mock",
        "provider": str(os.getenv("BYES_PLANNER_PROVIDER", "reference")).strip() or "reference",
        "endpoint": str(os.getenv("BYES_PLANNER_ENDPOINT", "")).strip() or None,
    }
    seg_targets = [str(item).strip() for item in runtime_cfg.inference_seg_targets if str(item).strip()]
    seg_prompt = runtime_cfg.inference_seg_prompt
    seg_prompt_present = isinstance(seg_prompt, dict)
    seg_prompt_budget = {
        "maxChars": max(0, int(runtime_cfg.inference_seg_prompt_max_chars)),
        "maxTargets": max(0, int(runtime_cfg.inference_seg_prompt_max_targets)),
        "maxBoxes": max(0, int(runtime_cfg.inference_seg_prompt_max_boxes)),
        "maxPoints": max(0, int(runtime_cfg.inference_seg_prompt_max_points)),
        "mode": str(runtime_cfg.inference_seg_prompt_budget_mode or "targets_text_boxes_points").strip()
        or "targets_text_boxes_points",
    }
    plan_context_pack_budget = resolve_plan_context_pack_budget_from_env()
    return {
        "segContext": {
            "defaultBudget": {
                "maxChars": int(DEFAULT_SEG_CONTEXT_BUDGET["maxChars"]),
                "maxSegments": int(DEFAULT_SEG_CONTEXT_BUDGET["maxSegments"]),
                "mode": str(DEFAULT_SEG_CONTEXT_BUDGET["mode"]),
            }
        },
        "slamContext": {
            "defaultBudget": {
                "maxChars": int(DEFAULT_SLAM_CONTEXT_BUDGET["maxChars"]),
                "mode": str(DEFAULT_SLAM_CONTEXT_BUDGET["mode"]),
            }
        },
        "povContext": {
            "defaultBudget": {
                "maxChars": int(pov_budget.get("maxChars", 2000)),
                "maxTokensApprox": int(pov_budget.get("maxTokensApprox", 500)),
                "mode": "decisions_plus_highlights",
            }
        },
        "plan": {
            "defaultBudget": {
                "maxChars": int(plan_budget.get("maxChars", 2000)),
                "maxTokensApprox": int(plan_budget.get("maxTokensApprox", 256)),
                "mode": str(plan_budget.get("mode", "decisions_plus_highlights")),
            },
            "defaultConstraints": {
                "allowConfirm": bool(plan_constraints.get("allowConfirm", True)),
                "allowHaptic": bool(plan_constraints.get("allowHaptic", False)),
                "maxActions": int(plan_constraints.get("maxActions", 3)),
            },
            "plannerDefaults": planner_defaults,
        },
        "planRequest": {
            "defaultPromptVersion": "v4",
            "includeSegContext": True,
            "includePovContext": True,
            "includeSlamContext": True,
            "includeCostmapContext": True,
        },
        "planContextPack": {
            "defaultBudget": {
                "maxChars": int(plan_context_pack_budget.get("maxChars", DEFAULT_PLAN_CONTEXT_PACK_BUDGET["maxChars"])),
                "mode": str(plan_context_pack_budget.get("mode", DEFAULT_PLAN_CONTEXT_PACK_BUDGET["mode"])),
            }
        },
        "costmapContext": {
            "defaultBudget": {
                "maxChars": int(DEFAULT_COSTMAP_CONTEXT_BUDGET["maxChars"]),
                "mode": str(DEFAULT_COSTMAP_CONTEXT_BUDGET["mode"]),
                "source": str(DEFAULT_COSTMAP_CONTEXT_SOURCE),
            }
        },
        "costmapFused": {
            "defaultFuse": {
                "alpha": float(DEFAULT_COSTMAP_FUSED_CONFIG["alpha"]),
                "decay": float(DEFAULT_COSTMAP_FUSED_CONFIG["decay"]),
                "windowFrames": int(DEFAULT_COSTMAP_FUSED_CONFIG["windowFrames"]),
                "shiftEnabled": bool(DEFAULT_COSTMAP_FUSED_CONFIG["shiftEnabled"]),
                "occupiedThresh": int(DEFAULT_COSTMAP_FUSED_CONFIG["occupiedThresh"]),
            }
        },
        "segPrompt": {
            "targets": seg_targets,
            "promptPresent": seg_prompt_present,
            "promptTextChars": len(str(seg_prompt.get("text", ""))) if seg_prompt_present else 0,
            "defaultBudget": seg_prompt_budget,
        },
        "riskThresholdDefaults": risk_threshold_defaults,
        "models": {
            "notes": "Use GET /api/models or scripts/verify_models.py for required model/env/endpoint checks.",
            "checkScript": "python Gateway/scripts/verify_models.py --json",
        },
    }


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


class PovContextBudgetRequest(BaseModel):
    maxChars: int = 2000
    maxTokensApprox: int = 500

    @model_validator(mode="after")
    def _validate_budget(self) -> "PovContextBudgetRequest":
        if int(self.maxChars) < 0:
            raise ValueError("budget.maxChars must be >= 0")
        if int(self.maxTokensApprox) < 0:
            raise ValueError("budget.maxTokensApprox must be >= 0")
        return self


class PovContextRequest(BaseModel):
    runPackage: str | None = None
    runId: str | None = None
    budget: PovContextBudgetRequest = PovContextBudgetRequest()
    mode: Literal["decisions_only", "decisions_plus_highlights", "full"] = "decisions_plus_highlights"

    @model_validator(mode="after")
    def _validate_source(self) -> "PovContextRequest":
        run_package = str(self.runPackage or "").strip()
        run_id = str(self.runId or "").strip()
        if not run_package and not run_id:
            raise ValueError("runPackage or runId is required")
        return self


class PlanBudgetRequest(BaseModel):
    maxChars: int = 2000
    maxTokensApprox: int = 256
    mode: Literal["decisions_only", "decisions_plus_highlights", "full"] = "decisions_plus_highlights"

    @model_validator(mode="after")
    def _validate_budget(self) -> "PlanBudgetRequest":
        if int(self.maxChars) < 0:
            raise ValueError("budget.maxChars must be >= 0")
        if int(self.maxTokensApprox) < 0:
            raise ValueError("budget.maxTokensApprox must be >= 0")
        return self


class PlanConstraintsRequest(BaseModel):
    allowConfirm: bool = True
    allowHaptic: bool = False
    maxActions: int = 3

    @model_validator(mode="after")
    def _validate_constraints(self) -> "PlanConstraintsRequest":
        if int(self.maxActions) <= 0:
            raise ValueError("constraints.maxActions must be >= 1")
        return self


class PlanContextPackOverrideRequest(BaseModel):
    maxChars: int | None = None
    slamMaxChars: int | None = None
    mode: Literal[
        "seg_plus_pov_plus_risk",
        "seg_plus_pov",
        "pov_plus_risk",
        "seg_only",
        "pov_only",
        "risk_only",
    ] | None = None

    @model_validator(mode="after")
    def _validate_override(self) -> "PlanContextPackOverrideRequest":
        if self.maxChars is None and self.mode is None and self.slamMaxChars is None:
            raise ValueError("contextPackOverride requires maxChars, slamMaxChars, or mode")
        if self.maxChars is not None and int(self.maxChars) < 0:
            raise ValueError("contextPackOverride.maxChars must be >= 0")
        if self.slamMaxChars is not None and int(self.slamMaxChars) < 0:
            raise ValueError("contextPackOverride.slamMaxChars must be >= 0")
        return self


class PlanGenerateRequest(BaseModel):
    runPackage: str | None = None
    runId: str | None = None
    frameSeq: int | None = 1
    budget: PlanBudgetRequest = PlanBudgetRequest()
    constraints: PlanConstraintsRequest = PlanConstraintsRequest()
    contextPackOverride: PlanContextPackOverrideRequest | None = None

    @model_validator(mode="after")
    def _validate_source(self) -> "PlanGenerateRequest":
        run_package = str(self.runPackage or "").strip()
        run_id = str(self.runId or "").strip()
        if not run_package and not run_id:
            raise ValueError("runPackage or runId is required")
        if self.frameSeq is not None and int(self.frameSeq) <= 0:
            raise ValueError("frameSeq must be >= 1 when provided")
        return self


class PlanExecuteRequest(BaseModel):
    plan: dict[str, Any]
    runPackage: str | None = None
    runId: str | None = None
    frameSeq: int | None = None


class FrameAckRequest(BaseModel):
    runId: str
    frameSeq: int
    feedbackTsMs: int
    kind: Literal["tts", "ar", "overlay", "haptic", "other", "any"] = "any"
    accepted: bool = True
    runPackage: str | None = None

    @model_validator(mode="after")
    def _validate_ack(self) -> "FrameAckRequest":
        if not str(self.runId or "").strip():
            raise ValueError("runId is required")
        if int(self.frameSeq) <= 0:
            raise ValueError("frameSeq must be >= 1")
        if int(self.feedbackTsMs) < 0:
            raise ValueError("feedbackTsMs must be >= 0")
        return self


class ConfirmResponseRequest(BaseModel):
    runId: str
    frameSeq: int
    confirmId: str
    accepted: bool
    runPackage: str | None = None

    @model_validator(mode="after")
    def _validate_confirm(self) -> "ConfirmResponseRequest":
        if not str(self.runId or "").strip():
            raise ValueError("runId is required")
        if int(self.frameSeq) <= 0:
            raise ValueError("frameSeq must be >= 1")
        if not str(self.confirmId or "").strip():
            raise ValueError("confirmId is required")
        return self


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
        self.ocr_backend = get_ocr_backend(self.config)
        self.risk_backend = get_risk_backend(self.config)
        self.seg_backend = get_seg_backend(self.config)
        self.depth_backend = get_depth_backend(self.config)
        self.slam_backend = get_slam_backend(self.config)
        self.costmap_fuser = CostmapFuser()
        self._inference_events: list[dict[str, Any]] = []
        self._inference_events_limit = 2048
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
        self.pov_store = PovStore()

    async def startup(self) -> None:
        self.run_packages_root.mkdir(parents=True, exist_ok=True)
        self.ocr_backend = get_ocr_backend(self.config)
        self.risk_backend = get_risk_backend(self.config)
        self.seg_backend = get_seg_backend(self.config)
        self.depth_backend = get_depth_backend(self.config)
        self.slam_backend = get_slam_backend(self.config)
        self._inference_events.clear()
        self.costmap_fuser.reset()
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

    def drain_inference_events(self) -> list[dict[str, Any]]:
        snapshot = list(self._inference_events)
        self._inference_events.clear()
        return snapshot

    async def _emit_inference_event(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        self._inference_events.append(dict(event))
        if len(self._inference_events) > self._inference_events_limit:
            self._inference_events = self._inference_events[-self._inference_events_limit :]
        if self.config.inference_emit_ws_events_v1:
            await self.connections.broadcast_json(event)

    @staticmethod
    def _extract_run_id(meta: dict[str, Any]) -> str | None:
        for key in ("runId", "sessionId", "session_id"):
            value = meta.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @staticmethod
    def _resolve_event_frame_seq(seq: int, meta: dict[str, Any]) -> int:
        event_frame_seq = int(max(1, int(seq)))
        for key in ("clientSeq", "frameSeq", "frame_seq", "seq"):
            raw_value = meta.get(key)
            if raw_value is None:
                continue
            try:
                parsed = int(raw_value)
            except Exception:
                continue
            if parsed > 0:
                event_frame_seq = int(parsed)
                break
        return int(max(1, event_frame_seq))

    @staticmethod
    def _normalize_seg_prompt(prompt: dict[str, Any] | None) -> dict[str, Any] | None:
        return normalize_prompt(prompt)

    @staticmethod
    def _build_seg_prompt_payload(
        prompt: dict[str, Any],
        *,
        backend: str | None,
        model: str | None,
        endpoint: str | None,
        budget: dict[str, Any] | None = None,
        pack_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        targets_raw = prompt.get("targets")
        text_raw = str(prompt.get("text", ""))
        boxes_raw = prompt.get("boxes")
        points_raw = prompt.get("points")
        meta_raw = prompt.get("meta")
        prompt_version = None
        if isinstance(meta_raw, dict):
            raw_prompt_version = meta_raw.get("promptVersion")
            text_version = "" if raw_prompt_version is None else str(raw_prompt_version).strip()
            prompt_version = text_version or None
        out_stats = pack_stats.get("out", {}) if isinstance(pack_stats, dict) and isinstance(pack_stats.get("out"), dict) else {}
        trunc_stats = (
            pack_stats.get("truncation", {})
            if isinstance(pack_stats, dict) and isinstance(pack_stats.get("truncation"), dict)
            else {}
        )
        complexity = (
            pack_stats.get("complexity", {})
            if isinstance(pack_stats, dict) and isinstance(pack_stats.get("complexity"), dict)
            else {}
        )
        warnings_count = int(pack_stats.get("warningsCount", 0) or 0) if isinstance(pack_stats, dict) else 0
        packed = bool(pack_stats.get("packed", False)) if isinstance(pack_stats, dict) else False
        budget_payload = {
            "maxChars": int(budget.get("maxChars", 0) or 0) if isinstance(budget, dict) else 0,
            "maxTargets": int(budget.get("maxTargets", 0) or 0) if isinstance(budget, dict) else 0,
            "maxBoxes": int(budget.get("maxBoxes", 0) or 0) if isinstance(budget, dict) else 0,
            "maxPoints": int(budget.get("maxPoints", 0) or 0) if isinstance(budget, dict) else 0,
            "mode": str(budget.get("mode", "")).strip() if isinstance(budget, dict) else "",
        }
        return {
            "targetsCount": int(out_stats.get("targets", len(targets_raw) if isinstance(targets_raw, list) else 0) or 0),
            "textChars": int(out_stats.get("textChars", len(text_raw)) or 0),
            "boxesCount": int(out_stats.get("boxes", len(boxes_raw) if isinstance(boxes_raw, list) else 0) or 0),
            "pointsCount": int(out_stats.get("points", len(points_raw) if isinstance(points_raw, list) else 0) or 0),
            "promptVersion": prompt_version,
            "backend": (str(backend or "").strip().lower() or None),
            "endpoint": (str(endpoint or "").strip() or None),
            "model": (str(model or "").strip() or None),
            "budget": budget_payload,
            "out": {
                "targetsCount": int(out_stats.get("targets", len(targets_raw) if isinstance(targets_raw, list) else 0) or 0),
                "textChars": int(out_stats.get("textChars", len(text_raw)) or 0),
                "boxesCount": int(out_stats.get("boxes", len(boxes_raw) if isinstance(boxes_raw, list) else 0) or 0),
                "pointsCount": int(out_stats.get("points", len(points_raw) if isinstance(points_raw, list) else 0) or 0),
                "charsTotal": int(
                    out_stats.get(
                        "charsTotal",
                        (
                            len(text_raw)
                            + (len(targets_raw) if isinstance(targets_raw, list) else 0)
                            + (len(boxes_raw) if isinstance(boxes_raw, list) else 0)
                            + (len(points_raw) if isinstance(points_raw, list) else 0)
                        ),
                    )
                    or 0
                ),
            },
            "truncation": {
                "targetsDropped": int(trunc_stats.get("targetsDropped", 0) or 0),
                "boxesDropped": int(trunc_stats.get("boxesDropped", 0) or 0),
                "pointsDropped": int(trunc_stats.get("pointsDropped", 0) or 0),
                "textCharsDropped": int(trunc_stats.get("textCharsDropped", 0) or 0),
            },
            "complexity": {
                "hasText": bool(complexity.get("hasText", False)),
                "hasBoxes": bool(complexity.get("hasBoxes", False)),
                "hasPoints": bool(complexity.get("hasPoints", False)),
                "hasTargets": bool(complexity.get("hasTargets", False)),
                "score": float(complexity.get("score", 0.0) or 0.0),
            },
            "packed": packed,
            "warningsCount": warnings_count,
        }

    async def _run_inference_for_frame(self, frame_bytes: bytes, seq: int, ts_ms: int, meta: dict[str, Any]) -> None:
        run_id = self._extract_run_id(meta)
        component = str(self.config.inference_event_component or "gateway")
        event_frame_seq = self._resolve_event_frame_seq(seq, meta)
        depth_payload_for_costmap: dict[str, Any] | None = None
        seg_payload_for_costmap: dict[str, Any] | None = None
        slam_payload_for_costmap: dict[str, Any] | None = None
        depth_backend_for_costmap = None
        depth_model_for_costmap = None
        depth_endpoint_for_costmap = None
        costmap_fused_payload: dict[str, Any] | None = None
        if self.config.inference_enable_ocr:
            ocr_started_ms = _now_ms()
            try:
                ocr_result = await self.ocr_backend.infer(
                    frame_bytes,
                    seq,
                    ts_ms,
                    run_id=run_id,
                    targets=None,
                    prompt=None,
                )
            except Exception as exc:  # noqa: BLE001
                ocr_result = OCRResult(status="error", error=exc.__class__.__name__, payload={"reason": exc.__class__.__name__})
            await emit_ocr_events(
                ocr_result,
                frame_seq=event_frame_seq,
                ts_ms=_now_ms(),
                started_ts_ms=ocr_started_ms,
                sink=self._emit_inference_event,
                run_id=run_id,
                component=component,
                backend=getattr(self.ocr_backend, "name", None),
                model=getattr(self.ocr_backend, "model_id", None),
                endpoint=getattr(self.ocr_backend, "endpoint", None),
            )

        if self.config.inference_enable_risk:
            risk_started_ms = _now_ms()
            try:
                risk_result = await self.risk_backend.infer(frame_bytes, seq, ts_ms)
            except Exception as exc:  # noqa: BLE001
                risk_result = RiskResult(
                    status="error",
                    error=exc.__class__.__name__,
                    payload={"reason": exc.__class__.__name__},
                    latency_ms=max(0, _now_ms() - risk_started_ms),
                )
            await emit_risk_events(
                risk_result,
                frame_seq=event_frame_seq,
                ts_ms=_now_ms(),
                started_ts_ms=risk_started_ms,
                sink=self._emit_inference_event,
                run_id=run_id,
                component=component,
                backend=getattr(self.risk_backend, "name", None),
                model=getattr(self.risk_backend, "model_id", None),
                endpoint=getattr(self.risk_backend, "endpoint", None),
            )

        if self.config.inference_enable_depth:
            depth_started_ms = _now_ms()
            depth_backend_name = getattr(self.depth_backend, "name", None)
            depth_model_id = getattr(self.depth_backend, "model_id", None)
            depth_endpoint = getattr(self.depth_backend, "endpoint", None)
            try:
                depth_result = await self.depth_backend.infer(
                    frame_bytes,
                    seq,
                    ts_ms,
                    run_id=run_id,
                    targets=None,
                )
            except Exception as exc:  # noqa: BLE001
                depth_result = DepthResult(
                    status="error",
                    error=exc.__class__.__name__,
                    payload={
                        "reason": exc.__class__.__name__,
                        "gridCount": 0,
                        "valuesCount": 0,
                    },
                    latency_ms=max(0, _now_ms() - depth_started_ms),
                )
            await emit_depth_events(
                depth_result,
                frame_seq=event_frame_seq,
                ts_ms=_now_ms(),
                started_ts_ms=depth_started_ms,
                sink=self._emit_inference_event,
                run_id=run_id,
                component=component,
                backend=depth_backend_name,
                model=depth_model_id,
                endpoint=depth_endpoint,
            )
            depth_payload_for_costmap = depth_result.payload if isinstance(depth_result.payload, dict) else {}
            if isinstance(depth_result.grid, dict):
                depth_payload_for_costmap = dict(depth_payload_for_costmap)
                depth_payload_for_costmap["grid"] = dict(depth_result.grid)
            depth_backend_for_costmap = depth_backend_name
            depth_model_for_costmap = depth_model_id
            depth_endpoint_for_costmap = depth_endpoint

        if self.config.inference_enable_slam:
            slam_started_ms = _now_ms()
            slam_backend_name = getattr(self.slam_backend, "name", None)
            slam_model_id = getattr(self.slam_backend, "model_id", None)
            slam_endpoint = getattr(self.slam_backend, "endpoint", None)
            try:
                slam_result = await self.slam_backend.infer(
                    frame_bytes,
                    seq,
                    ts_ms,
                    run_id=run_id,
                    targets=None,
                    prompt=None,
                )
            except Exception as exc:  # noqa: BLE001
                slam_result = SlamResult(
                    status="error",
                    error=exc.__class__.__name__,
                    payload={"reason": exc.__class__.__name__},
                    latency_ms=max(0, _now_ms() - slam_started_ms),
                )
            await emit_slam_pose_events(
                slam_result,
                frame_seq=event_frame_seq,
                ts_ms=_now_ms(),
                started_ts_ms=slam_started_ms,
                sink=self._emit_inference_event,
                run_id=run_id,
                component=component,
                backend=slam_backend_name,
                model=slam_model_id,
                endpoint=slam_endpoint,
            )
            slam_payload_for_costmap = slam_result.payload if isinstance(slam_result.payload, dict) else {}
            if isinstance(slam_result.pose, dict):
                slam_payload_for_costmap = dict(slam_payload_for_costmap)
                pose_obj = slam_payload_for_costmap.get("pose")
                pose_obj = pose_obj if isinstance(pose_obj, dict) else {}
                if "t" not in pose_obj and isinstance(slam_result.pose.get("t"), list):
                    pose_obj["t"] = list(slam_result.pose.get("t") or [])
                if "q" not in pose_obj and isinstance(slam_result.pose.get("q"), list):
                    pose_obj["q"] = list(slam_result.pose.get("q") or [])
                slam_payload_for_costmap["pose"] = pose_obj
                slam_payload_for_costmap.setdefault("trackingState", slam_result.tracking_state)

        if self.config.inference_enable_seg:
            seg_started_ms = _now_ms()
            seg_targets = [str(item).strip() for item in self.config.inference_seg_targets if str(item).strip()]
            seg_prompt = self._normalize_seg_prompt(self.config.inference_seg_prompt)
            seg_prompt_budget = {
                "maxChars": max(0, int(self.config.inference_seg_prompt_max_chars)),
                "maxTargets": max(0, int(self.config.inference_seg_prompt_max_targets)),
                "maxBoxes": max(0, int(self.config.inference_seg_prompt_max_boxes)),
                "maxPoints": max(0, int(self.config.inference_seg_prompt_max_points)),
                "mode": str(self.config.inference_seg_prompt_budget_mode or "targets_text_boxes_points").strip()
                or "targets_text_boxes_points",
            }
            packed_seg_prompt, seg_prompt_stats = pack_prompt(seg_prompt, budget=seg_prompt_budget)
            seg_backend_name = getattr(self.seg_backend, "name", None)
            seg_model_id = getattr(self.seg_backend, "model_id", None)
            seg_endpoint = getattr(self.seg_backend, "endpoint", None)
            if packed_seg_prompt is not None:
                seg_prompt_payload = self._build_seg_prompt_payload(
                    packed_seg_prompt,
                    backend=seg_backend_name,
                    model=seg_model_id,
                    endpoint=seg_endpoint,
                    budget=seg_prompt_budget,
                    pack_stats=seg_prompt_stats,
                )
                await self._emit_inference_event(
                    {
                        "schemaVersion": "byes.event.v1",
                        "tsMs": seg_started_ms,
                        "runId": run_id,
                        "frameSeq": event_frame_seq,
                        "component": component,
                        "category": "tool",
                        "name": "seg.prompt",
                        "phase": "result",
                        "status": "ok",
                        "latencyMs": None,
                        "payload": seg_prompt_payload,
                    }
                )
            try:
                seg_result = await self.seg_backend.infer(
                    frame_bytes,
                    seq,
                    ts_ms,
                    run_id=run_id,
                    targets=seg_targets or None,
                    prompt=packed_seg_prompt,
                    tracking=bool(self.config.inference_seg_tracking),
                )
            except Exception as exc:  # noqa: BLE001
                seg_result = SegResult(
                    status="error",
                    error=exc.__class__.__name__,
                    payload={
                        "reason": exc.__class__.__name__,
                        "segmentsCount": 0,
                        "targetsCount": len(seg_targets),
                        "targetsUsed": seg_targets,
                    },
                    latency_ms=max(0, _now_ms() - seg_started_ms),
                )
            await emit_seg_events(
                seg_result,
                frame_seq=event_frame_seq,
                ts_ms=_now_ms(),
                started_ts_ms=seg_started_ms,
                sink=self._emit_inference_event,
                run_id=run_id,
                component=component,
                backend=seg_backend_name,
                model=seg_model_id,
                endpoint=seg_endpoint,
            )
            seg_payload_for_costmap = seg_result.payload if isinstance(seg_result.payload, dict) else {}
            if isinstance(seg_result.segments, list):
                seg_payload_for_costmap = dict(seg_payload_for_costmap)
                seg_payload_for_costmap["segments"] = [row for row in seg_result.segments if isinstance(row, dict)]

        if self.config.inference_enable_costmap:
            costmap_started_ms = _now_ms()
            costmap_payload = build_local_costmap(
                run_id=run_id or "costmap-live",
                frame_seq=event_frame_seq,
                depth_payload=depth_payload_for_costmap,
                seg_payload=seg_payload_for_costmap,
                slam_payload=slam_payload_for_costmap,
                config={
                    "gridH": int(self.config.inference_costmap_grid_h),
                    "gridW": int(self.config.inference_costmap_grid_w),
                    "resolutionM": float(self.config.inference_costmap_resolution_m),
                    "depthThreshM": float(self.config.inference_costmap_depth_thresh_m),
                    "dynamicLabels": list(self.config.inference_costmap_dynamic_labels),
                },
                backend="local",
                model="local-costmap-v1",
                endpoint=None,
            )
            costmap_latency_ms = max(0, _now_ms() - costmap_started_ms)
            await self._emit_inference_event(
                {
                    "schemaVersion": "byes.event.v1",
                    "tsMs": _now_ms(),
                    "runId": run_id,
                    "frameSeq": event_frame_seq,
                    "component": component,
                    "category": "map",
                    "name": "map.costmap",
                    "phase": "result",
                    "status": "ok",
                    "latencyMs": int(costmap_latency_ms),
                    "payload": costmap_payload,
                }
            )
            fused_latency_ms = 0
            if self.config.inference_enable_costmap_fused:
                fused_started_ms = _now_ms()
                costmap_fused_payload = self.costmap_fuser.update(
                    run_id=run_id or "costmap-live",
                    frame_seq=event_frame_seq,
                    raw_costmap_payload=costmap_payload,
                    slam_payload=slam_payload_for_costmap,
                    config={
                        "alpha": float(self.config.inference_costmap_fused_alpha),
                        "decay": float(self.config.inference_costmap_fused_decay),
                        "windowFrames": int(self.config.inference_costmap_fused_window),
                        "shiftEnabled": bool(self.config.inference_costmap_fused_shift),
                        "shiftGateEnabled": bool(self.config.inference_costmap_fused_shift_gate),
                        "minTrackingRate": float(self.config.inference_costmap_fused_min_tracking_rate),
                        "maxLostStreak": int(self.config.inference_costmap_fused_max_lost_streak),
                        "maxAlignResidualP90Ms": float(
                            self.config.inference_costmap_fused_max_align_residual_p90_ms
                        ),
                        "maxAteRmseM": float(self.config.inference_costmap_fused_max_ate_rmse_m),
                        "maxRpeTransRmseM": float(self.config.inference_costmap_fused_max_rpe_trans_rmse_m),
                        "slamTrajPreferred": str(self.config.inference_slam_traj_preferred),
                        "slamTrajAllowed": [str(item) for item in self.config.inference_slam_traj_allowed],
                        "occupiedThresh": int(self.config.inference_costmap_occupied_thresh),
                    },
                    backend="local",
                    model="local-costmap-fused-v1",
                    endpoint=None,
                )
                fused_latency_ms = max(0, _now_ms() - fused_started_ms)
                await self._emit_inference_event(
                    {
                        "schemaVersion": "byes.event.v1",
                        "tsMs": _now_ms(),
                        "runId": run_id,
                        "frameSeq": event_frame_seq,
                        "component": component,
                        "category": "map",
                        "name": "map.costmap_fused",
                        "phase": "result",
                        "status": "ok",
                        "latencyMs": int(fused_latency_ms),
                        "payload": costmap_fused_payload,
                    }
                )

            context_source = str(
                self.config.inference_costmap_context_source or DEFAULT_COSTMAP_CONTEXT_SOURCE
            ).strip().lower()
            if context_source not in {"auto", "raw", "fused"}:
                context_source = DEFAULT_COSTMAP_CONTEXT_SOURCE
            selected_source = "raw"
            selected_costmap_payload = costmap_payload
            selected_latency_ms = costmap_latency_ms
            if context_source == "fused" and isinstance(costmap_fused_payload, dict):
                selected_source = "fused"
                selected_costmap_payload = costmap_fused_payload
                selected_latency_ms = fused_latency_ms
            elif context_source == "auto" and isinstance(costmap_fused_payload, dict):
                selected_source = "fused"
                selected_costmap_payload = costmap_fused_payload
                selected_latency_ms = fused_latency_ms

            costmap_context_payload = build_costmap_context_pack(
                costmap_payload=selected_costmap_payload,
                budget={
                    "maxChars": int(self.config.inference_costmap_context_max_chars),
                    "mode": str(self.config.inference_costmap_context_mode or DEFAULT_COSTMAP_CONTEXT_BUDGET["mode"]).strip()
                    or str(DEFAULT_COSTMAP_CONTEXT_BUDGET["mode"]),
                },
                source=selected_source,
            )
            await self._emit_inference_event(
                {
                    "schemaVersion": "byes.event.v1",
                    "tsMs": _now_ms(),
                    "runId": run_id,
                    "frameSeq": event_frame_seq,
                    "component": component,
                    "category": "map",
                    "name": "map.costmap_context",
                    "phase": "result",
                    "status": "ok",
                    "latencyMs": int(selected_latency_ms),
                    "payload": costmap_context_payload,
                }
            )

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
        await self._run_inference_for_frame(frame_bytes, seq, request_start_ms, enriched_meta)
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
        self._inference_events.clear()
        self.costmap_fuser.reset()
        with _FRAME_E2E_STATE_LOCK:
            _FRAME_E2E_STATE.clear()
        with _FRAME_USER_E2E_STATE_LOCK:
            _FRAME_USER_E2E_STATE.clear()
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
    captureTsMs: int | None = Form(default=None),
    deviceId: str | None = Form(default=None),
    deviceTimeBase: str | None = Form(default=None),
) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type", "")).lower()
    frame_bytes: bytes | None = None
    raw_meta: str | None = None
    recv_ts_ms = _now_ms()

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
    run_id = gateway._extract_run_id(meta_json) or "unknown-run"  # noqa: SLF001
    event_frame_seq = gateway._resolve_event_frame_seq(seq, meta_json)  # noqa: SLF001
    capture_ts_ms = _to_nonnegative_int_or_none(meta_json.get("captureTsMs"))
    if capture_ts_ms is None:
        capture_ts_ms = _to_nonnegative_int_or_none(captureTsMs)
    device_id = str(meta_json.get("deviceId", "")).strip() or (str(deviceId or "").strip() or None)
    raw_time_base = str(meta_json.get("deviceTimeBase", "")).strip() or (str(deviceTimeBase or "").strip() or None)
    frame_input_payload = _build_frame_input_payload(
        run_id=run_id,
        frame_seq=event_frame_seq,
        capture_ts_ms=capture_ts_ms,
        recv_ts_ms=recv_ts_ms,
        device_time_base=raw_time_base,
        device_id=device_id,
    )
    frame_input_event = _build_byes_event(
        run_id=run_id,
        frame_seq=event_frame_seq,
        category="frame",
        name="frame.input",
        payload=frame_input_payload,
    )
    await gateway._emit_inference_event(frame_input_event)  # noqa: SLF001

    t0_for_state = _to_nonnegative_int_or_none(capture_ts_ms)
    if t0_for_state is None:
        t0_for_state = int(max(0, recv_ts_ms))
    _frame_user_e2e_mark_input(run_id, event_frame_seq, t0_for_state)

    run_package_raw = str(meta_json.get("runPackage", "")).strip()
    if run_package_raw:
        cleanup_dir: Path | None = None
        try:
            run_package_dir, cleanup_dir, can_write_events = await _resolve_context_run_package_dir_async(
                run_package_raw=run_package_raw,
                run_id=run_id,
            )
            if can_write_events:
                _manifest_path, manifest = _load_run_package_manifest(run_package_dir)
                events_path = _resolve_events_v1_path(run_package_dir, manifest)
                _append_events_v1_rows(events_path, [frame_input_event])
                _frame_e2e_begin_state(
                    events_path=events_path,
                    run_id=run_id,
                    frame_seq=event_frame_seq,
                    t0_hint_ms=t0_for_state,
                )
        except Exception:
            pass
        finally:
            if cleanup_dir is not None and cleanup_dir.exists():
                shutil.rmtree(cleanup_dir, ignore_errors=True)
    return {"ok": True, "bytes": len(frame_bytes), "seq": seq}


@app.post("/api/frame/ack")
async def frame_ack(request: FrameAckRequest) -> dict[str, Any]:
    cleanup_dir: Path | None = None
    run_id = str(request.runId or "").strip() or "unknown-run"
    frame_seq = int(max(1, int(request.frameSeq)))
    feedback_ts_ms = int(max(0, int(request.feedbackTsMs)))
    ack_payload = _build_frame_ack_payload(
        run_id=run_id,
        frame_seq=frame_seq,
        feedback_ts_ms=feedback_ts_ms,
        kind=request.kind,
        accepted=bool(request.accepted),
    )
    ack_event = _build_byes_event(
        run_id=run_id,
        frame_seq=frame_seq,
        category="frame",
        name="frame.ack",
        payload=ack_payload,
    )
    await gateway._emit_inference_event(ack_event)  # noqa: SLF001
    _frame_user_e2e_mark_ack(run_id, frame_seq, feedback_ts_ms, bool(request.accepted))

    user_e2e_ms: int | None = None
    snapshot = _frame_user_e2e_snapshot(run_id, frame_seq)
    if isinstance(snapshot, dict):
        t0_ms = _to_nonnegative_int_or_none(snapshot.get("t0Ms"))
        if t0_ms is not None:
            user_e2e_ms = int(feedback_ts_ms - t0_ms)

    try:
        run_package_raw = str(request.runPackage or "").strip() or None
        run_package_dir: Path | None = None
        can_write_events = False
        try:
            run_package_dir, cleanup_dir, can_write_events = await _resolve_context_run_package_dir_async(
                run_package_raw=run_package_raw,
                run_id=run_id,
            )
        except HTTPException as ex:
            if int(ex.status_code) != 404:
                raise
            run_package_dir = None
            can_write_events = False
        if run_package_dir is not None and can_write_events:
            _manifest_path, manifest = _load_run_package_manifest(run_package_dir)
            events_path = _resolve_events_v1_path(run_package_dir, manifest)
            _append_events_v1_rows(events_path, [ack_event])
            _try_append_frame_user_e2e_event(
                events_path=events_path,
                run_id=run_id,
                frame_seq=frame_seq,
            )
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    return {
        "ok": True,
        "runId": run_id,
        "frameSeq": frame_seq,
        "feedbackTsMs": feedback_ts_ms,
        "kind": str(request.kind),
        "accepted": bool(request.accepted),
        "userE2eMs": user_e2e_ms,
    }


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


def _summarize_pov_ir(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    decisions = payload.get("decisionPoints")
    events = payload.get("events")
    highlights = payload.get("highlights")
    tokens = payload.get("tokens")
    return {
        "runId": run_id,
        "counts": {
            "decisions": sum(1 for item in decisions if isinstance(item, dict)) if isinstance(decisions, list) else 0,
            "events": sum(1 for item in events if isinstance(item, dict)) if isinstance(events, list) else 0,
            "highlights": sum(1 for item in highlights if isinstance(item, dict)) if isinstance(highlights, list) else 0,
            "tokens": sum(1 for item in tokens if isinstance(item, dict)) if isinstance(tokens, list) else 0,
        },
        "createdAtMs": _now_ms(),
        "present": True,
    }


@app.post("/api/pov/ingest")
async def ingest_pov_ir(
    payload: dict[str, Any],
    runPackage: str | None = None,
    runId: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be object")
    ok, errors = validate_pov_ir(payload, strict=True)
    if not ok:
        raise HTTPException(status_code=400, detail={"message": "pov ir schema invalid", "errors": errors})

    event_run_id = str(payload.get("runId", "")).strip()
    if not event_run_id:
        raise HTTPException(status_code=400, detail="pov ir runId is required")
    gateway.pov_store.set(event_run_id, payload)
    summary = _summarize_pov_ir(payload, event_run_id)

    event_row = _build_byes_event(
        run_id=event_run_id,
        frame_seq=1,
        category="pov",
        name="pov.ingest",
        payload={
            "runId": event_run_id,
            "decisions": int(summary["counts"]["decisions"]),
            "events": int(summary["counts"]["events"]),
            "highlights": int(summary["counts"]["highlights"]),
            "tokens": int(summary["counts"]["tokens"]),
        },
    )
    await gateway._emit_inference_event(event_row)  # noqa: SLF001

    cleanup_dir: Path | None = None
    run_package_dir: Path | None = None
    can_write_events = False
    try:
        run_package_text = str(runPackage or "").strip()
        run_id_text = str(runId or "").strip() or event_run_id
        if run_package_text:
            run_package_dir, cleanup_dir, can_write_events = _resolve_context_run_package_input(run_package_text)
        else:
            try:
                run_package_dir, cleanup_dir, can_write_events = await _resolve_context_run_package_dir_async(
                    run_package_raw=None,
                    run_id=run_id_text,
                )
            except HTTPException:
                run_package_dir = None
                can_write_events = False
        if run_package_dir is not None and can_write_events:
            _manifest_path, manifest = _load_run_package_manifest(run_package_dir)
            events_path = _resolve_events_v1_path(run_package_dir, manifest)
            _append_events_v1_rows(events_path, [event_row])
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    return {"ok": True, **summary}


@app.get("/api/pov/latest")
async def get_latest_pov(runId: str) -> dict[str, Any]:
    run_id = str(runId or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="runId is required")
    summary = gateway.pov_store.summary(run_id)
    if not bool(summary.get("present")):
        raise HTTPException(status_code=404, detail=f"pov not found for runId: {run_id}")
    return {"ok": True, **summary}


@app.get("/api/seg/context")
async def get_seg_context(
    runId: str,
    maxChars: int = int(DEFAULT_SEG_CONTEXT_BUDGET["maxChars"]),
    maxSegments: int = int(DEFAULT_SEG_CONTEXT_BUDGET["maxSegments"]),
    mode: Literal["topk_by_score", "label_grouped"] = str(DEFAULT_SEG_CONTEXT_BUDGET["mode"]),
) -> dict[str, Any]:
    run_id = str(runId or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="runId is required")

    budget = {
        "maxChars": max(0, int(maxChars)),
        "maxSegments": max(0, int(maxSegments)),
        "mode": str(mode or DEFAULT_SEG_CONTEXT_BUDGET["mode"]).strip() or str(DEFAULT_SEG_CONTEXT_BUDGET["mode"]),
    }
    cleanup_dir: Path | None = None
    events_rows: list[dict[str, Any]] = []
    try:
        try:
            run_package_dir, cleanup_dir, _can_write_events = await _resolve_context_run_package_dir_async(
                run_package_raw=None,
                run_id=run_id,
            )
            _manifest_path, manifest = _load_run_package_manifest(run_package_dir)
            events_rows, _events_path = load_events_v1_rows(run_package_dir, manifest)
        except HTTPException as ex:
            if int(ex.status_code) != 404:
                raise
            events_rows = []

        if not events_rows:
            for row in gateway._inference_events:  # noqa: SLF001
                if not isinstance(row, dict):
                    continue
                if str(row.get("runId", "")).strip() != run_id:
                    continue
                events_rows.append(dict(row))

        if not events_rows:
            raise HTTPException(status_code=404, detail=f"no events found for runId: {run_id}")

        context = build_seg_context_from_events(events_rows, budget=budget)
        return context
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


@app.get("/api/slam/context")
async def get_slam_context(
    runId: str,
    frameSeq: int | None = None,
    maxChars: int = int(DEFAULT_SLAM_CONTEXT_BUDGET["maxChars"]),
    mode: Literal["last_pose_and_health"] = str(DEFAULT_SLAM_CONTEXT_BUDGET["mode"]),
) -> dict[str, Any]:
    run_id = str(runId or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="runId is required")

    budget = {
        "maxChars": max(0, int(maxChars)),
        "mode": str(mode or DEFAULT_SLAM_CONTEXT_BUDGET["mode"]).strip() or str(DEFAULT_SLAM_CONTEXT_BUDGET["mode"]),
    }
    requested_frame_seq = int(frameSeq) if frameSeq is not None else None

    cleanup_dir: Path | None = None
    events_rows: list[dict[str, Any]] = []
    slam_error_payload: dict[str, Any] | None = None
    alignment_payload: dict[str, Any] | None = None
    try:
        try:
            run_package_dir, cleanup_dir, _can_write_events = await _resolve_context_run_package_dir_async(
                run_package_raw=None,
                run_id=run_id,
            )
            _manifest_path, manifest = _load_run_package_manifest(run_package_dir)
            events_rows, _events_path = load_events_v1_rows(run_package_dir, manifest)

            report_path = run_package_dir / "report.json"
            if report_path.exists() and report_path.is_file():
                try:
                    report_payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    report_payload = None
                if isinstance(report_payload, dict):
                    quality_payload = report_payload.get("quality")
                    quality_payload = quality_payload if isinstance(quality_payload, dict) else {}
                    slam_error = quality_payload.get("slamError")
                    if isinstance(slam_error, dict):
                        slam_error_payload = slam_error
                    slam_quality = quality_payload.get("slam")
                    slam_quality = slam_quality if isinstance(slam_quality, dict) else {}
                    slam_alignment = slam_quality.get("alignment")
                    if isinstance(slam_alignment, dict):
                        alignment_payload = slam_alignment
        except HTTPException as ex:
            if int(ex.status_code) != 404:
                raise
            events_rows = []

        if not events_rows:
            for row in gateway._inference_events:  # noqa: SLF001
                if not isinstance(row, dict):
                    continue
                if str(row.get("runId", "")).strip() != run_id:
                    continue
                events_rows.append(dict(row))

        if not events_rows:
            raise HTTPException(status_code=404, detail=f"no SLAM events found for runId: {run_id}")

        context_run_id = run_id
        has_requested_run_id = False
        fallback_run_id = ""
        for row in events_rows:
            if not isinstance(row, dict):
                continue
            event = row.get("event") if isinstance(row.get("event"), dict) else row
            if not isinstance(event, dict):
                continue
            if str(event.get("name", "")).strip().lower() != "slam.pose":
                continue
            event_run_id = str(event.get("runId", "")).strip()
            if event_run_id and not fallback_run_id:
                fallback_run_id = event_run_id
            if not event_run_id or event_run_id == run_id:
                has_requested_run_id = True
        if not has_requested_run_id and fallback_run_id:
            context_run_id = fallback_run_id

        return build_slam_context_pack(
            run_id=context_run_id,
            frame_seq=requested_frame_seq,
            events_v1=events_rows,
            budget=budget,
            slam_error=slam_error_payload,
            alignment=alignment_payload,
        )
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


@app.get("/api/plan/context")
async def get_plan_context(
    runId: str,
    maxChars: int = int(DEFAULT_PLAN_CONTEXT_PACK_BUDGET["maxChars"]),
    mode: Literal[
        "seg_plus_pov_plus_risk",
        "seg_plus_pov",
        "pov_plus_risk",
        "seg_only",
        "pov_only",
        "risk_only",
    ] = str(DEFAULT_PLAN_CONTEXT_PACK_BUDGET["mode"]),
    ctxMaxChars: int | None = None,
    ctxMode: Literal[
        "seg_plus_pov_plus_risk",
        "seg_plus_pov",
        "pov_plus_risk",
        "seg_only",
        "pov_only",
        "risk_only",
    ] | None = None,
) -> dict[str, Any]:
    run_id = str(runId or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="runId is required")

    budget_override_used = ctxMaxChars is not None or ctxMode is not None
    effective_max_chars = int(ctxMaxChars) if ctxMaxChars is not None else int(maxChars)
    effective_mode = (
        str(ctxMode).strip()
        if ctxMode is not None
        else str(mode or DEFAULT_PLAN_CONTEXT_PACK_BUDGET["mode"]).strip()
    )
    budget = {
        "maxChars": max(0, int(effective_max_chars)),
        "mode": effective_mode or str(DEFAULT_PLAN_CONTEXT_PACK_BUDGET["mode"]),
    }

    cleanup_dir: Path | None = None
    events_rows: list[dict[str, Any]] = []
    pov_ir_payload: dict[str, Any] | None = None
    try:
        try:
            run_package_dir, cleanup_dir, _can_write_events = await _resolve_context_run_package_dir_async(
                run_package_raw=None,
                run_id=run_id,
            )
            _manifest_path, manifest = _load_run_package_manifest(run_package_dir)
            events_rows, _events_path = load_events_v1_rows(run_package_dir, manifest)
            if str(manifest.get("povIrJson", "")).strip():
                _manifest, pov_ir_payload, _pov_path = _load_pov_ir_for_context(run_package_dir)
        except HTTPException as ex:
            if int(ex.status_code) != 404:
                raise
            events_rows = []

        if not isinstance(pov_ir_payload, dict):
            store_pov = gateway.pov_store.get(run_id)
            pov_ir_payload = store_pov if isinstance(store_pov, dict) else None

        if not events_rows:
            for row in gateway._inference_events:  # noqa: SLF001
                if not isinstance(row, dict):
                    continue
                if str(row.get("runId", "")).strip() != run_id:
                    continue
                events_rows.append(dict(row))

        if not events_rows and not isinstance(pov_ir_payload, dict):
            raise HTTPException(status_code=404, detail=f"no plan context data found for runId: {run_id}")

        seg_context_budget = {
            "maxChars": int(DEFAULT_SEG_CONTEXT_BUDGET["maxChars"]),
            "maxSegments": int(DEFAULT_SEG_CONTEXT_BUDGET["maxSegments"]),
            "mode": str(DEFAULT_SEG_CONTEXT_BUDGET["mode"]),
        }
        seg_context_raw = build_seg_context_from_events(events_rows, budget=seg_context_budget)
        seg_stats = seg_context_raw.get("stats")
        seg_stats = seg_stats if isinstance(seg_stats, dict) else {}
        seg_out = seg_stats.get("out")
        seg_out = seg_out if isinstance(seg_out, dict) else {}
        seg_context = seg_context_raw if int(seg_out.get("segments", 0) or 0) > 0 else None

        pov_context: dict[str, Any] | None = None
        if isinstance(pov_ir_payload, dict):
            pov_budget = PovContextBudgetRequest().model_dump()
            ctx = build_context_pack(pov_ir_payload, budget=pov_budget, mode="decisions_plus_highlights")
            ctx_text = render_context_text(ctx)
            pov_context = finalize_context_pack_text(ctx, ctx_text, _now_ms())

        risk_summary = extract_risk_summary(events_rows, frame_seq=None)
        context_pack = build_plan_context_pack(
            run_id=run_id,
            seg_context=seg_context,
            pov_context=pov_context,
            risk_context=risk_summary,
            budget=budget,
        )
        response_payload = dict(context_pack) if isinstance(context_pack, dict) else {}
        response_payload["budgetOverrideUsed"] = bool(budget_override_used)
        return response_payload
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


@app.get("/api/contracts")
async def contracts_index() -> dict[str, Any]:
    try:
        lock_path, lock_payload = _load_contract_lock()
    except FileNotFoundError as ex:
        raise HTTPException(status_code=500, detail=str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(status_code=500, detail=str(ex)) from ex
    versions = lock_payload.get("versions", {})
    versions = versions if isinstance(versions, dict) else {}
    return {
        "schemaVersion": "byes.contracts.index.v1",
        "generatedAtMs": _now_ms(),
        "lockPath": str(lock_path),
        "lockGeneratedAtMs": int(lock_payload.get("generatedAtMs", 0) or 0),
        "versions": versions,
        "runtimeDefaults": _runtime_contract_defaults(),
    }


@app.get("/api/models")
async def models_index() -> dict[str, Any]:
    return build_model_manifest(load_config())


def _resolve_planner_provider(request_provider: str | None) -> str:
    provider_text = str(request_provider or "").strip().lower()
    if provider_text in {"reference", "llm", "pov"}:
        return provider_text
    env_provider = str(os.getenv("BYES_PLANNER_PROVIDER", "")).strip().lower()
    if env_provider in {"reference", "llm", "pov"}:
        return env_provider
    return "reference"


@app.post("/api/pov/context")
async def build_pov_context(request: PovContextRequest) -> dict[str, Any]:
    started_at = time.perf_counter()
    cleanup_dir: Path | None = None
    try:
        run_package_dir, cleanup_dir, can_write_events = await _resolve_context_run_package_dir_async(
            run_package_raw=request.runPackage,
            run_id=request.runId,
        )
        manifest, pov_ir, _pov_path = _load_pov_ir_for_context(run_package_dir)
        budget_payload = {
            "maxChars": int(request.budget.maxChars),
            "maxTokensApprox": int(request.budget.maxTokensApprox),
        }
        context_pack = build_context_pack(pov_ir, budget=budget_payload, mode=request.mode)
        text_payload = render_context_text(context_pack)
        context_pack = finalize_context_pack_text(context_pack, text_payload, _now_ms())

        run_id = str(context_pack.get("runId", "")).strip()
        if not run_id:
            run_id = str(manifest.get("runId", "")).strip() or run_package_dir.name
            context_pack["runId"] = run_id

        latency_ms = int(max(0, (time.perf_counter() - started_at) * 1000.0))
        if can_write_events:
            stats = context_pack.get("stats", {})
            stats = stats if isinstance(stats, dict) else {}
            out_stats = stats.get("out", {})
            out_stats = out_stats if isinstance(out_stats, dict) else {}
            truncation = stats.get("truncation", {})
            truncation = truncation if isinstance(truncation, dict) else {}
            _try_append_pov_context_event(
                run_package_dir=run_package_dir,
                manifest=manifest,
                run_id=run_id,
                latency_ms=latency_ms,
                budget=context_pack.get("budget", {}),
                out_stats=out_stats,
                truncation=truncation,
            )
        return context_pack
    except HTTPException:
        raise
    except ValidationError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"pov context build failed: {ex}") from ex
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


@app.post("/api/plan")
async def generate_plan(request: PlanGenerateRequest, provider: str | None = None) -> dict[str, Any]:
    started_at = time.perf_counter()
    started_at_ms = _now_ms()
    cleanup_dir: Path | None = None
    try:
        run_package_dir: Path | None = None
        can_write_events = False
        manifest: dict[str, Any] = {}
        pov_ir_from_package: dict[str, Any] | None = None
        events_rows: list[dict[str, Any]] = []
        run_package_text = str(request.runPackage or "").strip()
        run_id_text = str(request.runId or "").strip()

        if run_package_text:
            run_package_dir, cleanup_dir, can_write_events = await _resolve_context_run_package_dir_async(
                run_package_raw=run_package_text,
                run_id=run_id_text or None,
            )
        elif run_id_text:
            try:
                run_package_dir, cleanup_dir, can_write_events = await _resolve_context_run_package_dir_async(
                    run_package_raw=None,
                    run_id=run_id_text,
                )
            except HTTPException as ex:
                if int(ex.status_code) != 404:
                    raise
                run_package_dir = None
                can_write_events = False

        if run_package_dir is not None:
            manifest, pov_ir_from_package, _ = _load_pov_ir_for_context(run_package_dir)
            events_rows, _ = load_events_v1_rows(run_package_dir, manifest)

        frame_seq = int(request.frameSeq) if isinstance(request.frameSeq, int) and request.frameSeq > 0 else None
        safe_frame_seq = int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1
        run_id = (
            str(request.runId or "").strip()
            or str(manifest.get("runId", "")).strip()
            or str((pov_ir_from_package or {}).get("runId", "")).strip()
            or (run_package_dir.name if run_package_dir is not None else "")
        )
        frame_e2e_events_path: Path | None = None
        if can_write_events and run_package_dir is not None:
            frame_e2e_events_path = _resolve_events_v1_path(run_package_dir, manifest)
            _frame_e2e_begin_state(
                events_path=frame_e2e_events_path,
                run_id=run_id,
                frame_seq=safe_frame_seq,
                t0_hint_ms=started_at_ms,
            )
        planner_provider = _resolve_planner_provider(provider)
        inline_pov_ir = gateway.pov_store.get(run_id) if planner_provider == "pov" else None
        pov_ir = inline_pov_ir if isinstance(inline_pov_ir, dict) else pov_ir_from_package
        if not isinstance(pov_ir, dict):
            raise HTTPException(status_code=404, detail=f"pov ir not found for runId: {run_id}")
        budget_payload = {
            "maxChars": int(request.budget.maxChars),
            "maxTokensApprox": int(request.budget.maxTokensApprox),
        }
        constraints_payload = {
            "allowConfirm": bool(request.constraints.allowConfirm),
            "allowHaptic": bool(request.constraints.allowHaptic),
            "maxActions": int(request.constraints.maxActions),
        }
        context_pack_override_payload: dict[str, Any] | None = None
        slam_context_override_payload: dict[str, Any] | None = None
        if isinstance(request.contextPackOverride, PlanContextPackOverrideRequest):
            override_payload: dict[str, Any] = {}
            if request.contextPackOverride.maxChars is not None:
                override_payload["maxChars"] = int(max(0, int(request.contextPackOverride.maxChars)))
            if request.contextPackOverride.mode is not None:
                override_payload["mode"] = str(request.contextPackOverride.mode).strip()
            if override_payload:
                context_pack_override_payload = override_payload
            slam_override_payload: dict[str, Any] = {}
            if request.contextPackOverride.slamMaxChars is not None:
                slam_override_payload["maxChars"] = int(max(0, int(request.contextPackOverride.slamMaxChars)))
            if slam_override_payload:
                slam_context_override_payload = slam_override_payload
        bundle = generate_action_plan(
            pov_ir=pov_ir,
            run_id=run_id,
            frame_seq=frame_seq,
            budget=budget_payload,
            mode=request.budget.mode,
            constraints=constraints_payload,
            events_rows=events_rows,
            run_package_path=str(run_package_dir) if run_package_dir is not None else None,
            planner_provider=planner_provider,
            planner_pov_ir=inline_pov_ir if isinstance(inline_pov_ir, dict) else None,
            plan_context_pack_budget=context_pack_override_payload,
            slam_context_budget=slam_context_override_payload,
            costmap_context_source=str(
                gateway.config.inference_costmap_context_source or DEFAULT_COSTMAP_CONTEXT_SOURCE
            ).strip().lower()
            or DEFAULT_COSTMAP_CONTEXT_SOURCE,
        )
        plan_payload = bundle.get("plan")
        if not isinstance(plan_payload, dict):
            raise RuntimeError("planner returned invalid plan payload")
        latency_ms = int(max(0, (time.perf_counter() - started_at) * 1000.0))
        if can_write_events and run_package_dir is not None:
            actions_payload = plan_payload.get("actions")
            actions_payload = actions_payload if isinstance(actions_payload, list) else []
            stop_count = sum(
                1 for action in actions_payload if str(action.get("type", "")).strip().lower() == "stop"
            )
            confirm_action_count = sum(
                1 for action in actions_payload if str(action.get("type", "")).strip().lower() == "confirm"
            )
            blocking_count = sum(1 for action in actions_payload if bool(action.get("blocking")))
            planner = bundle.get("planner", {})
            planner = planner if isinstance(planner, dict) else {}
            guardrails = bundle.get("guardrailsApplied", [])
            guardrails = guardrails if isinstance(guardrails, list) else []
            findings = bundle.get("findings", [])
            findings = findings if isinstance(findings, list) else []
            plan_request_payload = bundle.get("planRequest")
            plan_request_payload = plan_request_payload if isinstance(plan_request_payload, dict) else {}
            plan_context_pack_payload = bundle.get("planContextPack")
            plan_context_pack_payload = plan_context_pack_payload if isinstance(plan_context_pack_payload, dict) else {}
            plan_context_alignment_payload = compute_plan_context_alignment(plan_request_payload, plan_payload)
            planner_rule_payload = {
                "applied": bool(planner.get("ruleApplied")),
                "ruleVersion": planner.get("ruleVersion"),
                "hazardHint": planner.get("ruleHazardHint"),
                "matchedKeywords": planner.get("matchedKeywords"),
                "segContextUsed": planner.get("segContextUsed"),
                "riskLevel": str(plan_payload.get("riskLevel", "low")),
            }
            _try_append_plan_events(
                run_package_dir=run_package_dir,
                manifest=manifest,
                run_id=run_id,
                frame_seq=frame_seq,
                latency_ms=latency_ms,
                planner=planner,
                risk_level=str(plan_payload.get("riskLevel", "low")),
                actions_count=len(actions_payload),
                stop_count=stop_count,
                confirm_action_count=confirm_action_count,
                blocking_count=blocking_count,
                guardrails_applied=[str(item) for item in guardrails if str(item).strip()],
                findings_count=len(findings),
                plan_request=plan_request_payload,
                rule_payload=planner_rule_payload,
                alignment_payload=plan_context_alignment_payload,
                plan_context_pack=plan_context_pack_payload,
                t0_hint_ms=started_at_ms,
            )
            if frame_e2e_events_path is not None:
                _try_append_frame_e2e_event(
                    events_path=frame_e2e_events_path,
                    run_id=run_id,
                    frame_seq=safe_frame_seq,
                    t1_ms=_now_ms(),
                    t0_hint_ms=started_at_ms,
                    plan_ms=latency_ms,
                    plan_present=True,
                )
        else:
            planner = bundle.get("planner", {})
            planner = planner if isinstance(planner, dict) else {}
            plan_request_payload = bundle.get("planRequest")
            plan_request_payload = plan_request_payload if isinstance(plan_request_payload, dict) else {}
            plan_context_pack_payload = bundle.get("planContextPack")
            plan_context_pack_payload = plan_context_pack_payload if isinstance(plan_context_pack_payload, dict) else {}
            plan_context_alignment_payload = compute_plan_context_alignment(plan_request_payload, plan_payload)
            actions_payload = plan_payload.get("actions")
            actions_payload = actions_payload if isinstance(actions_payload, list) else []
            guardrails = bundle.get("guardrailsApplied", [])
            guardrails = guardrails if isinstance(guardrails, list) else []
            findings = bundle.get("findings", [])
            findings = findings if isinstance(findings, list) else []
            plan_context_pack_row = _build_byes_event(
                run_id=run_id or "pov-live",
                frame_seq=frame_seq or 1,
                category="plan",
                name="plan.context_pack",
                latency_ms=latency_ms,
                payload=_build_plan_context_pack_event_payload(plan_context_pack_payload),
            )
            plan_request_row = _build_byes_event(
                run_id=run_id or "pov-live",
                frame_seq=frame_seq or 1,
                category="plan",
                name="plan.request",
                latency_ms=latency_ms,
                payload=_build_plan_request_event_payload(plan_request_payload, planner),
            )
            plan_row = _build_byes_event(
                run_id=run_id or "pov-live",
                frame_seq=frame_seq or 1,
                category="plan",
                name="plan.generate",
                latency_ms=latency_ms,
                payload={
                    "backend": planner.get("backend"),
                    "model": planner.get("model"),
                    "endpoint": planner.get("endpoint"),
                    "plannerProvider": planner.get("plannerProvider") or planner.get("provider"),
                    "promptVersion": planner.get("promptVersion"),
                    "fallbackUsed": planner.get("fallbackUsed"),
                    "fallbackReason": planner.get("fallbackReason"),
                    "jsonValid": planner.get("jsonValid"),
                    "contextUsedDetail": planner.get("contextUsedDetail"),
                    "riskLevel": str(plan_payload.get("riskLevel", "low")),
                    "actionsCount": len(actions_payload),
                },
            )
            context_alignment_row = _build_byes_event(
                run_id=run_id or "pov-live",
                frame_seq=frame_seq or 1,
                category="plan",
                name="plan.context_alignment",
                latency_ms=latency_ms,
                payload=_build_plan_context_alignment_event_payload(plan_context_alignment_payload),
            )
            rule_row = None
            if bool(planner.get("ruleApplied")):
                rule_row = _build_byes_event(
                    run_id=run_id or "pov-live",
                    frame_seq=frame_seq or 1,
                    category="plan",
                    name="plan.rule_applied",
                    latency_ms=latency_ms,
                    payload={
                        "ruleVersion": planner.get("ruleVersion"),
                        "hazardHint": planner.get("ruleHazardHint"),
                        "matchedKeywords": [str(item) for item in (planner.get("matchedKeywords") or [])[:3]],
                        "segContextUsed": bool(planner.get("segContextUsed")),
                        "riskLevel": str(plan_payload.get("riskLevel", "low")),
                    },
                )
            safety_row = _build_byes_event(
                run_id=run_id or "pov-live",
                frame_seq=frame_seq or 1,
                category="safety",
                name="safety.kernel",
                latency_ms=latency_ms,
                payload={
                    "riskLevel": str(plan_payload.get("riskLevel", "low")),
                    "guardrailsApplied": [str(item) for item in guardrails if str(item).strip()],
                    "findingsCount": len(findings),
                },
            )
            existing_rows = list(gateway._inference_events)  # noqa: SLF001
            existing_rows.extend(
                [
                    plan_context_pack_row,
                    plan_request_row,
                    plan_row,
                    context_alignment_row,
                ]
            )
            if isinstance(rule_row, dict):
                existing_rows.append(rule_row)
            existing_rows.append(safety_row)
            has_frame_e2e = _frame_e2e_exists_in_rows(
                existing_rows,
                run_id=run_id or "pov-live",
                frame_seq=frame_seq or 1,
            )
            await gateway._emit_inference_event(plan_context_pack_row)  # noqa: SLF001
            await gateway._emit_inference_event(plan_request_row)  # noqa: SLF001
            await gateway._emit_inference_event(plan_row)  # noqa: SLF001
            await gateway._emit_inference_event(context_alignment_row)  # noqa: SLF001
            if isinstance(rule_row, dict):
                await gateway._emit_inference_event(rule_row)  # noqa: SLF001
            await gateway._emit_inference_event(safety_row)  # noqa: SLF001
            if not has_frame_e2e:
                frame_e2e_row = _build_frame_e2e_event(
                    rows=existing_rows,
                    run_id=run_id or "pov-live",
                    frame_seq=frame_seq or 1,
                    t1_ms=_now_ms(),
                    t0_hint_ms=started_at_ms,
                )
                await gateway._emit_inference_event(frame_e2e_row)  # noqa: SLF001
        return plan_payload
    except HTTPException:
        raise
    except ValidationError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"plan generation failed: {ex}") from ex
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


@app.post("/api/plan/execute")
async def execute_plan(request: PlanExecuteRequest) -> dict[str, Any]:
    started_at = time.perf_counter()
    started_at_ms = _now_ms()
    cleanup_dir: Path | None = None
    try:
        plan = request.plan if isinstance(request.plan, dict) else None
        if not isinstance(plan, dict):
            raise HTTPException(status_code=400, detail="plan must be object")
        if str(plan.get("schemaVersion", "")).strip() != "byes.action_plan.v1":
            raise HTTPException(status_code=400, detail="plan.schemaVersion must be byes.action_plan.v1")
        command_rows: list[dict[str, Any]] = []

        def _emit_command(command: dict[str, Any]) -> None:
            command_rows.append(dict(command))

        result = execute_action_plan(plan, emit_event_fn=_emit_command, now_ms_fn=_now_ms)
        run_package_text = str(request.runPackage or "").strip()
        run_id_text = str(request.runId or "").strip()
        if run_package_text or run_id_text:
            run_package_dir, cleanup_dir, can_write_events = await _resolve_context_run_package_dir_async(
                run_package_raw=run_package_text or None,
                run_id=run_id_text or None,
            )
            _manifest_path, manifest = _load_run_package_manifest(run_package_dir)
            events_path = _resolve_events_v1_path(run_package_dir, manifest)
            run_id = str(plan.get("runId", "")).strip() or str(manifest.get("runId", "")).strip() or run_package_dir.name
            frame_seq: int | None = None
            if isinstance(request.frameSeq, int) and request.frameSeq > 0:
                frame_seq = int(request.frameSeq)
            elif isinstance(plan.get("frameSeq"), int) and int(plan.get("frameSeq", 0)) > 0:
                frame_seq = int(plan.get("frameSeq", 0))
            safe_frame_seq = int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1
            _frame_e2e_begin_state(
                events_path=events_path,
                run_id=run_id,
                frame_seq=safe_frame_seq,
                t0_hint_ms=started_at_ms,
            )
            latency_ms = int(max(0, (time.perf_counter() - started_at) * 1000.0))
            if can_write_events:
                ui_events = _build_ui_events_from_commands(command_rows)
                _try_append_plan_execute_event(
                    run_package_dir=run_package_dir,
                    manifest=manifest,
                    run_id=run_id,
                    frame_seq=frame_seq,
                    latency_ms=latency_ms,
                    executed_count=int(result.get("executedCount", 0) or 0),
                    blocked_count=int(result.get("blockedCount", 0) or 0),
                    pending_confirm_count=int(result.get("pendingConfirmCount", 0) or 0),
                    ui_events=ui_events,
                    t0_hint_ms=started_at_ms,
                )
                _try_append_frame_e2e_event(
                    events_path=events_path,
                    run_id=run_id,
                    frame_seq=safe_frame_seq,
                    t1_ms=_now_ms(),
                    t0_hint_ms=started_at_ms,
                    execute_ms=latency_ms,
                    execute_present=True,
                )
        return result
    except HTTPException:
        raise
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"plan execution failed: {ex}") from ex
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


@app.post("/api/confirm/response")
async def confirm_response(request: ConfirmResponseRequest) -> dict[str, Any]:
    started_at_ms = _now_ms()
    cleanup_dir: Path | None = None
    try:
        run_package_dir, cleanup_dir, _can_write_events = await _resolve_context_run_package_dir_async(
            run_package_raw=request.runPackage,
            run_id=request.runId,
        )
        _manifest_path, manifest = _load_run_package_manifest(run_package_dir)
        events_path = _resolve_events_v1_path(run_package_dir, manifest)
        if not events_path.exists() or not events_path.is_file():
            raise HTTPException(status_code=404, detail="eventsV1Jsonl not found")

        run_id = str(request.runId).strip()
        frame_seq = int(request.frameSeq)
        confirm_id = str(request.confirmId).strip()
        accepted = bool(request.accepted)
        _frame_e2e_begin_state(
            events_path=events_path,
            run_id=run_id,
            frame_seq=frame_seq,
            t0_hint_ms=started_at_ms,
        )
        now_ms = _now_ms()
        request_ts = _find_confirm_request_ts_ms(
            events_path,
            run_id=run_id,
            frame_seq=frame_seq,
            confirm_id=confirm_id,
        )
        latency_ms: int | None = None
        if request_ts is not None and now_ms >= request_ts:
            latency_ms = int(now_ms - request_ts)

        rows: list[dict[str, Any]] = [
            _build_byes_event(
                run_id=run_id,
                frame_seq=frame_seq,
                category="ui",
                name="ui.confirm_response",
                latency_ms=latency_ms,
                payload={
                    "confirmId": confirm_id,
                    "accepted": accepted,
                    "latencyMs": latency_ms,
                },
            )
        ]
        wrote_guardrail_stop = False
        if not accepted and _is_latest_risk_level_critical(events_path, run_id=run_id, frame_seq=frame_seq):
            rows.append(
                _build_byes_event(
                    run_id=run_id,
                    frame_seq=frame_seq,
                    category="ui",
                    name="ui.command",
                    payload={
                        "commandType": "stop",
                        "actionId": f"guardrail-stop-{confirm_id}",
                        "reason": "confirm_rejected_critical",
                    },
                )
            )
            wrote_guardrail_stop = True

        _append_events_v1_rows(events_path, rows)
        _try_append_frame_e2e_event(
            events_path=events_path,
            run_id=run_id,
            frame_seq=frame_seq,
            t1_ms=_now_ms(),
            t0_hint_ms=started_at_ms,
            confirm_ms=latency_ms,
            confirm_present=True,
        )
        return {
            "ok": True,
            "runId": run_id,
            "frameSeq": frame_seq,
            "confirmId": confirm_id,
            "accepted": accepted,
            "latencyMs": latency_ms,
            "guardrailStopIssued": wrote_guardrail_stop,
        }
    except HTTPException:
        raise
    except ValidationError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"confirm response failed: {ex}") from ex
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


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
    max_confirm_timeouts: int | None = None,
    max_critical_misses: int | None = None,
    max_risk_latency_p90: int | None = None,
    max_risk_latency_max: int | None = None,
    max_ocr_cer: float | None = None,
    min_ocr_exact_match_rate: float | None = None,
    min_ocr_coverage: float | None = None,
    max_ocr_latency_p90: int | None = None,
    min_seg_f1_50: float | None = None,
    min_seg_coverage: float | None = None,
    min_seg_track_coverage: float | None = None,
    min_seg_tracks_total: int | None = None,
    max_seg_id_switches: int | None = None,
    min_depth_delta1: float | None = None,
    max_depth_absrel: float | None = None,
    min_depth_coverage: float | None = None,
    max_depth_latency_p90: int | None = None,
    min_costmap_coverage: float | None = None,
    max_costmap_latency_p90: int | None = None,
    max_costmap_dynamic_filter_rate_mean: float | None = None,
    min_costmap_fused_coverage: float | None = None,
    max_costmap_fused_latency_p90: int | None = None,
    min_costmap_fused_iou_p90: float | None = None,
    max_costmap_fused_flicker_rate_mean: float | None = None,
    max_costmap_fused_shift_gate_reject_rate: float | None = None,
    min_costmap_fused_shift_used_rate: float | None = None,
    min_slam_tracking_rate: float | None = None,
    max_slam_lost_rate: float | None = None,
    max_slam_latency_p90: int | None = None,
    max_slam_align_residual_p90: int | None = None,
    max_slam_ate_rmse: float | None = None,
    max_slam_rpe_trans_rmse: float | None = None,
    min_seg_mask_f1_50: float | None = None,
    min_seg_mask_coverage: float | None = None,
    max_seg_latency_p90: int | None = None,
    max_frame_e2e_p90: int | None = None,
    max_frame_e2e_max: int | None = None,
    max_frame_user_e2e_p90: int | None = None,
    max_frame_user_e2e_max: int | None = None,
    max_frame_user_e2e_tts_p90: int | None = None,
    max_frame_user_e2e_ar_p90: int | None = None,
    min_ack_kind_diversity: int | None = None,
    max_models_missing_required: int | None = None,
    max_seg_ctx_chars: int | None = None,
    max_seg_ctx_trunc_dropped: int | None = None,
    max_plan_req_seg_chars_p90: int | None = None,
    max_plan_req_seg_trunc_dropped: int | None = None,
    plan_req_fallback_used: str = "any",
    min_plan_seg_ctx_coverage: float | None = None,
    min_plan_pov_ctx_coverage: float | None = None,
    min_plan_slam_ctx_coverage: float | None = None,
    require_plan_ctx_used: str = "any",
    require_plan_slam_ctx_used: str = "any",
    require_plan_costmap_ctx_used: str = "any",
    max_plan_ctx_trunc_rate: float | None = None,
    min_plan_ctx_chars_p90: int | None = None,
    require_slam_ctx_present: str = "any",
    max_slam_ctx_trunc_rate: float | None = None,
    min_slam_tracking_rate_mean: float | None = None,
    min_seg_prompt_text_chars: int | None = None,
    max_seg_prompt_trunc_rate: float | None = None,
    max_seg_prompt_trunc_dropped: int | None = None,
    has_pov: str = "any",
    min_pov_decisions: int | None = None,
    has_pov_context: str = "any",
    min_pov_context_token_approx: int | None = None,
    has_plan: str = "any",
    plan_fallback_used: str = "any",
    max_plan_latency_p90: int | None = None,
    max_plan_overcautious_rate: float | None = None,
    max_plan_guardrail_override_rate: float | None = None,
    max_plan_guardrails: int | None = None,
    min_plan_score: float | None = None,
    plan_risk_level: str | None = None,
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
        max_confirm_timeouts=max_confirm_timeouts,
        max_critical_misses=max_critical_misses,
        max_risk_latency_p90=max_risk_latency_p90,
        max_risk_latency_max=max_risk_latency_max,
        max_ocr_cer=max_ocr_cer,
        min_ocr_exact_match_rate=min_ocr_exact_match_rate,
        min_ocr_coverage=min_ocr_coverage,
        max_ocr_latency_p90=max_ocr_latency_p90,
        min_seg_f1_50=min_seg_f1_50,
        min_seg_coverage=min_seg_coverage,
        min_seg_track_coverage=min_seg_track_coverage,
        min_seg_tracks_total=min_seg_tracks_total,
        max_seg_id_switches=max_seg_id_switches,
        min_depth_delta1=min_depth_delta1,
        max_depth_absrel=max_depth_absrel,
        min_depth_coverage=min_depth_coverage,
        max_depth_latency_p90=max_depth_latency_p90,
        min_costmap_coverage=min_costmap_coverage,
        max_costmap_latency_p90=max_costmap_latency_p90,
        max_costmap_dynamic_filter_rate_mean=max_costmap_dynamic_filter_rate_mean,
        min_costmap_fused_coverage=min_costmap_fused_coverage,
        max_costmap_fused_latency_p90=max_costmap_fused_latency_p90,
        min_costmap_fused_iou_p90=min_costmap_fused_iou_p90,
        max_costmap_fused_flicker_rate_mean=max_costmap_fused_flicker_rate_mean,
        max_costmap_fused_shift_gate_reject_rate=max_costmap_fused_shift_gate_reject_rate,
        min_costmap_fused_shift_used_rate=min_costmap_fused_shift_used_rate,
        min_slam_tracking_rate=min_slam_tracking_rate,
        max_slam_lost_rate=max_slam_lost_rate,
        max_slam_latency_p90=max_slam_latency_p90,
        max_slam_align_residual_p90=max_slam_align_residual_p90,
        max_slam_ate_rmse=max_slam_ate_rmse,
        max_slam_rpe_trans_rmse=max_slam_rpe_trans_rmse,
        min_seg_mask_f1_50=min_seg_mask_f1_50,
        min_seg_mask_coverage=min_seg_mask_coverage,
        max_seg_latency_p90=max_seg_latency_p90,
        max_frame_e2e_p90=max_frame_e2e_p90,
        max_frame_e2e_max=max_frame_e2e_max,
        max_frame_user_e2e_p90=max_frame_user_e2e_p90,
        max_frame_user_e2e_max=max_frame_user_e2e_max,
        max_frame_user_e2e_tts_p90=max_frame_user_e2e_tts_p90,
        max_frame_user_e2e_ar_p90=max_frame_user_e2e_ar_p90,
        min_ack_kind_diversity=min_ack_kind_diversity,
        max_models_missing_required=max_models_missing_required,
        max_seg_ctx_chars=max_seg_ctx_chars,
        max_seg_ctx_trunc_dropped=max_seg_ctx_trunc_dropped,
        max_plan_req_seg_chars_p90=max_plan_req_seg_chars_p90,
        max_plan_req_seg_trunc_dropped=max_plan_req_seg_trunc_dropped,
        plan_req_fallback_used=plan_req_fallback_used,
        min_plan_seg_ctx_coverage=min_plan_seg_ctx_coverage,
        min_plan_pov_ctx_coverage=min_plan_pov_ctx_coverage,
        min_plan_slam_ctx_coverage=min_plan_slam_ctx_coverage,
        require_plan_ctx_used=require_plan_ctx_used,
        require_plan_slam_ctx_used=require_plan_slam_ctx_used,
        require_plan_costmap_ctx_used=require_plan_costmap_ctx_used,
        max_plan_ctx_trunc_rate=max_plan_ctx_trunc_rate,
        min_plan_ctx_chars_p90=min_plan_ctx_chars_p90,
        require_slam_ctx_present=require_slam_ctx_present,
        max_slam_ctx_trunc_rate=max_slam_ctx_trunc_rate,
        min_slam_tracking_rate_mean=min_slam_tracking_rate_mean,
        min_seg_prompt_text_chars=min_seg_prompt_text_chars,
        max_seg_prompt_trunc_rate=max_seg_prompt_trunc_rate,
        max_seg_prompt_trunc_dropped=max_seg_prompt_trunc_dropped,
        has_pov=has_pov,
        min_pov_decisions=min_pov_decisions,
        has_pov_context=has_pov_context,
        min_pov_context_token_approx=min_pov_context_token_approx,
        has_plan=has_plan,
        plan_fallback_used=plan_fallback_used,
        max_plan_latency_p90=max_plan_latency_p90,
        max_plan_overcautious_rate=max_plan_overcautious_rate,
        max_plan_guardrail_override_rate=max_plan_guardrail_override_rate,
        max_plan_guardrails=max_plan_guardrails,
        min_plan_score=min_plan_score,
        plan_risk_level=plan_risk_level,
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
            "max_confirm_timeouts": max_confirm_timeouts,
            "max_critical_misses": max_critical_misses,
            "max_risk_latency_p90": max_risk_latency_p90,
            "max_risk_latency_max": max_risk_latency_max,
            "max_ocr_cer": max_ocr_cer,
            "min_ocr_exact_match_rate": min_ocr_exact_match_rate,
            "min_ocr_coverage": min_ocr_coverage,
            "max_ocr_latency_p90": max_ocr_latency_p90,
            "min_seg_f1_50": min_seg_f1_50,
            "min_seg_coverage": min_seg_coverage,
            "min_seg_track_coverage": min_seg_track_coverage,
            "min_seg_tracks_total": min_seg_tracks_total,
            "max_seg_id_switches": max_seg_id_switches,
            "min_depth_delta1": min_depth_delta1,
            "max_depth_absrel": max_depth_absrel,
            "min_depth_coverage": min_depth_coverage,
            "max_depth_latency_p90": max_depth_latency_p90,
            "min_costmap_coverage": min_costmap_coverage,
            "max_costmap_latency_p90": max_costmap_latency_p90,
            "max_costmap_dynamic_filter_rate_mean": max_costmap_dynamic_filter_rate_mean,
            "min_costmap_fused_coverage": min_costmap_fused_coverage,
            "max_costmap_fused_latency_p90": max_costmap_fused_latency_p90,
            "min_costmap_fused_iou_p90": min_costmap_fused_iou_p90,
            "max_costmap_fused_flicker_rate_mean": max_costmap_fused_flicker_rate_mean,
            "max_costmap_fused_shift_gate_reject_rate": max_costmap_fused_shift_gate_reject_rate,
            "min_costmap_fused_shift_used_rate": min_costmap_fused_shift_used_rate,
            "min_slam_tracking_rate": min_slam_tracking_rate,
            "max_slam_lost_rate": max_slam_lost_rate,
            "max_slam_latency_p90": max_slam_latency_p90,
            "max_slam_align_residual_p90": max_slam_align_residual_p90,
            "max_slam_ate_rmse": max_slam_ate_rmse,
            "max_slam_rpe_trans_rmse": max_slam_rpe_trans_rmse,
            "min_seg_mask_f1_50": min_seg_mask_f1_50,
            "min_seg_mask_coverage": min_seg_mask_coverage,
            "max_seg_latency_p90": max_seg_latency_p90,
            "max_frame_e2e_p90": max_frame_e2e_p90,
            "max_frame_e2e_max": max_frame_e2e_max,
            "max_frame_user_e2e_p90": max_frame_user_e2e_p90,
            "max_frame_user_e2e_max": max_frame_user_e2e_max,
            "max_frame_user_e2e_tts_p90": max_frame_user_e2e_tts_p90,
            "max_frame_user_e2e_ar_p90": max_frame_user_e2e_ar_p90,
            "min_ack_kind_diversity": min_ack_kind_diversity,
            "max_models_missing_required": max_models_missing_required,
            "max_seg_ctx_chars": max_seg_ctx_chars,
            "max_seg_ctx_trunc_dropped": max_seg_ctx_trunc_dropped,
            "max_plan_req_seg_chars_p90": max_plan_req_seg_chars_p90,
            "max_plan_req_seg_trunc_dropped": max_plan_req_seg_trunc_dropped,
            "plan_req_fallback_used": plan_req_fallback_used,
            "min_plan_seg_ctx_coverage": min_plan_seg_ctx_coverage,
            "min_plan_pov_ctx_coverage": min_plan_pov_ctx_coverage,
            "min_plan_slam_ctx_coverage": min_plan_slam_ctx_coverage,
            "require_plan_ctx_used": require_plan_ctx_used,
            "require_plan_slam_ctx_used": require_plan_slam_ctx_used,
            "require_plan_costmap_ctx_used": require_plan_costmap_ctx_used,
            "max_plan_ctx_trunc_rate": max_plan_ctx_trunc_rate,
            "min_plan_ctx_chars_p90": min_plan_ctx_chars_p90,
            "require_slam_ctx_present": require_slam_ctx_present,
            "max_slam_ctx_trunc_rate": max_slam_ctx_trunc_rate,
            "min_slam_tracking_rate_mean": min_slam_tracking_rate_mean,
            "min_seg_prompt_text_chars": min_seg_prompt_text_chars,
            "max_seg_prompt_trunc_rate": max_seg_prompt_trunc_rate,
            "max_seg_prompt_trunc_dropped": max_seg_prompt_trunc_dropped,
            "has_pov": has_pov,
            "min_pov_decisions": min_pov_decisions,
            "has_pov_context": has_pov_context,
            "min_pov_context_token_approx": min_pov_context_token_approx,
            "has_plan": has_plan,
            "plan_fallback_used": plan_fallback_used,
            "max_plan_latency_p90": max_plan_latency_p90,
            "max_plan_overcautious_rate": max_plan_overcautious_rate,
            "max_plan_guardrail_override_rate": max_plan_guardrail_override_rate,
            "max_plan_guardrails": max_plan_guardrails,
            "min_plan_score": min_plan_score,
            "plan_risk_level": plan_risk_level,
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
    max_confirm_timeouts: int | None = None,
    max_critical_misses: int | None = None,
    max_risk_latency_p90: int | None = None,
    max_risk_latency_max: int | None = None,
    max_ocr_cer: float | None = None,
    min_ocr_exact_match_rate: float | None = None,
    min_ocr_coverage: float | None = None,
    max_ocr_latency_p90: int | None = None,
    min_seg_f1_50: float | None = None,
    min_seg_coverage: float | None = None,
    min_seg_track_coverage: float | None = None,
    min_seg_tracks_total: int | None = None,
    max_seg_id_switches: int | None = None,
    min_depth_delta1: float | None = None,
    max_depth_absrel: float | None = None,
    min_depth_coverage: float | None = None,
    max_depth_latency_p90: int | None = None,
    min_costmap_coverage: float | None = None,
    max_costmap_latency_p90: int | None = None,
    max_costmap_dynamic_filter_rate_mean: float | None = None,
    min_costmap_fused_coverage: float | None = None,
    max_costmap_fused_latency_p90: int | None = None,
    min_costmap_fused_iou_p90: float | None = None,
    max_costmap_fused_flicker_rate_mean: float | None = None,
    max_costmap_fused_shift_gate_reject_rate: float | None = None,
    min_costmap_fused_shift_used_rate: float | None = None,
    min_slam_tracking_rate: float | None = None,
    max_slam_lost_rate: float | None = None,
    max_slam_latency_p90: int | None = None,
    max_slam_align_residual_p90: int | None = None,
    max_slam_ate_rmse: float | None = None,
    max_slam_rpe_trans_rmse: float | None = None,
    min_seg_mask_f1_50: float | None = None,
    min_seg_mask_coverage: float | None = None,
    max_seg_latency_p90: int | None = None,
    max_frame_e2e_p90: int | None = None,
    max_frame_e2e_max: int | None = None,
    max_frame_user_e2e_p90: int | None = None,
    max_frame_user_e2e_max: int | None = None,
    max_frame_user_e2e_tts_p90: int | None = None,
    max_frame_user_e2e_ar_p90: int | None = None,
    min_ack_kind_diversity: int | None = None,
    max_models_missing_required: int | None = None,
    max_seg_ctx_chars: int | None = None,
    max_seg_ctx_trunc_dropped: int | None = None,
    max_plan_req_seg_chars_p90: int | None = None,
    max_plan_req_seg_trunc_dropped: int | None = None,
    plan_req_fallback_used: str = "any",
    min_plan_seg_ctx_coverage: float | None = None,
    min_plan_pov_ctx_coverage: float | None = None,
    min_plan_slam_ctx_coverage: float | None = None,
    require_plan_ctx_used: str = "any",
    require_plan_slam_ctx_used: str = "any",
    max_plan_ctx_trunc_rate: float | None = None,
    min_plan_ctx_chars_p90: int | None = None,
    require_slam_ctx_present: str = "any",
    max_slam_ctx_trunc_rate: float | None = None,
    min_slam_tracking_rate_mean: float | None = None,
    min_seg_prompt_text_chars: int | None = None,
    max_seg_prompt_trunc_rate: float | None = None,
    max_seg_prompt_trunc_dropped: int | None = None,
    has_pov: str = "any",
    min_pov_decisions: int | None = None,
    has_pov_context: str = "any",
    min_pov_context_token_approx: int | None = None,
    has_plan: str = "any",
    plan_fallback_used: str = "any",
    max_plan_latency_p90: int | None = None,
    max_plan_overcautious_rate: float | None = None,
    max_plan_guardrail_override_rate: float | None = None,
    require_plan_costmap_ctx_used: str = "any",
    max_plan_guardrails: int | None = None,
    min_plan_score: float | None = None,
    plan_risk_level: str | None = None,
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
        max_confirm_timeouts=max_confirm_timeouts,
        max_critical_misses=max_critical_misses,
        max_risk_latency_p90=max_risk_latency_p90,
        max_risk_latency_max=max_risk_latency_max,
        max_ocr_cer=max_ocr_cer,
        min_ocr_exact_match_rate=min_ocr_exact_match_rate,
        min_ocr_coverage=min_ocr_coverage,
        max_ocr_latency_p90=max_ocr_latency_p90,
        min_seg_f1_50=min_seg_f1_50,
        min_seg_coverage=min_seg_coverage,
        min_seg_track_coverage=min_seg_track_coverage,
        min_seg_tracks_total=min_seg_tracks_total,
        max_seg_id_switches=max_seg_id_switches,
            min_depth_delta1=min_depth_delta1,
            max_depth_absrel=max_depth_absrel,
            min_depth_coverage=min_depth_coverage,
            max_depth_latency_p90=max_depth_latency_p90,
            min_costmap_coverage=min_costmap_coverage,
            max_costmap_latency_p90=max_costmap_latency_p90,
            max_costmap_dynamic_filter_rate_mean=max_costmap_dynamic_filter_rate_mean,
            min_costmap_fused_coverage=min_costmap_fused_coverage,
            max_costmap_fused_latency_p90=max_costmap_fused_latency_p90,
            min_costmap_fused_iou_p90=min_costmap_fused_iou_p90,
            max_costmap_fused_flicker_rate_mean=max_costmap_fused_flicker_rate_mean,
            max_costmap_fused_shift_gate_reject_rate=max_costmap_fused_shift_gate_reject_rate,
            min_costmap_fused_shift_used_rate=min_costmap_fused_shift_used_rate,
            min_slam_tracking_rate=min_slam_tracking_rate,
        max_slam_lost_rate=max_slam_lost_rate,
        max_slam_latency_p90=max_slam_latency_p90,
        max_slam_align_residual_p90=max_slam_align_residual_p90,
        max_slam_ate_rmse=max_slam_ate_rmse,
        max_slam_rpe_trans_rmse=max_slam_rpe_trans_rmse,
        min_seg_mask_f1_50=min_seg_mask_f1_50,
        min_seg_mask_coverage=min_seg_mask_coverage,
        max_seg_latency_p90=max_seg_latency_p90,
        max_frame_e2e_p90=max_frame_e2e_p90,
        max_frame_e2e_max=max_frame_e2e_max,
        max_frame_user_e2e_p90=max_frame_user_e2e_p90,
        max_frame_user_e2e_max=max_frame_user_e2e_max,
        max_frame_user_e2e_tts_p90=max_frame_user_e2e_tts_p90,
        max_frame_user_e2e_ar_p90=max_frame_user_e2e_ar_p90,
        min_ack_kind_diversity=min_ack_kind_diversity,
        max_models_missing_required=max_models_missing_required,
        max_seg_ctx_chars=max_seg_ctx_chars,
        max_seg_ctx_trunc_dropped=max_seg_ctx_trunc_dropped,
        max_plan_req_seg_chars_p90=max_plan_req_seg_chars_p90,
        max_plan_req_seg_trunc_dropped=max_plan_req_seg_trunc_dropped,
        plan_req_fallback_used=plan_req_fallback_used,
        min_plan_seg_ctx_coverage=min_plan_seg_ctx_coverage,
        min_plan_pov_ctx_coverage=min_plan_pov_ctx_coverage,
        min_plan_slam_ctx_coverage=min_plan_slam_ctx_coverage,
        require_plan_ctx_used=require_plan_ctx_used,
        require_plan_slam_ctx_used=require_plan_slam_ctx_used,
        require_plan_costmap_ctx_used=require_plan_costmap_ctx_used,
        max_plan_ctx_trunc_rate=max_plan_ctx_trunc_rate,
        min_plan_ctx_chars_p90=min_plan_ctx_chars_p90,
        require_slam_ctx_present=require_slam_ctx_present,
        max_slam_ctx_trunc_rate=max_slam_ctx_trunc_rate,
        min_slam_tracking_rate_mean=min_slam_tracking_rate_mean,
        min_seg_prompt_text_chars=min_seg_prompt_text_chars,
        max_seg_prompt_trunc_rate=max_seg_prompt_trunc_rate,
        max_seg_prompt_trunc_dropped=max_seg_prompt_trunc_dropped,
        has_pov=has_pov,
        min_pov_decisions=min_pov_decisions,
        has_pov_context=has_pov_context,
        min_pov_context_token_approx=min_pov_context_token_approx,
        has_plan=has_plan,
        plan_fallback_used=plan_fallback_used,
        max_plan_latency_p90=max_plan_latency_p90,
        max_plan_overcautious_rate=max_plan_overcautious_rate,
        max_plan_guardrail_override_rate=max_plan_guardrail_override_rate,
        max_plan_guardrails=max_plan_guardrails,
        min_plan_score=min_plan_score,
        plan_risk_level=plan_risk_level,
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
    max_confirm_timeouts: int | None = None,
    max_critical_misses: int | None = None,
    max_risk_latency_p90: int | None = None,
    max_risk_latency_max: int | None = None,
    max_ocr_cer: float | None = None,
    min_ocr_exact_match_rate: float | None = None,
    min_ocr_coverage: float | None = None,
    max_ocr_latency_p90: int | None = None,
    min_seg_f1_50: float | None = None,
    min_seg_coverage: float | None = None,
    min_seg_track_coverage: float | None = None,
    min_seg_tracks_total: int | None = None,
    max_seg_id_switches: int | None = None,
    min_depth_delta1: float | None = None,
    max_depth_absrel: float | None = None,
    min_depth_coverage: float | None = None,
    max_depth_latency_p90: int | None = None,
    min_costmap_coverage: float | None = None,
    max_costmap_latency_p90: int | None = None,
    max_costmap_dynamic_filter_rate_mean: float | None = None,
    min_costmap_fused_coverage: float | None = None,
    max_costmap_fused_latency_p90: int | None = None,
    min_costmap_fused_iou_p90: float | None = None,
    max_costmap_fused_flicker_rate_mean: float | None = None,
    max_costmap_fused_shift_gate_reject_rate: float | None = None,
    min_costmap_fused_shift_used_rate: float | None = None,
    min_slam_tracking_rate: float | None = None,
    max_slam_lost_rate: float | None = None,
    max_slam_latency_p90: int | None = None,
    max_slam_align_residual_p90: int | None = None,
    max_slam_ate_rmse: float | None = None,
    max_slam_rpe_trans_rmse: float | None = None,
    min_seg_mask_f1_50: float | None = None,
    min_seg_mask_coverage: float | None = None,
    max_seg_latency_p90: int | None = None,
    max_frame_e2e_p90: int | None = None,
    max_frame_e2e_max: int | None = None,
    max_frame_user_e2e_p90: int | None = None,
    max_frame_user_e2e_max: int | None = None,
    max_frame_user_e2e_tts_p90: int | None = None,
    max_frame_user_e2e_ar_p90: int | None = None,
    min_ack_kind_diversity: int | None = None,
    max_models_missing_required: int | None = None,
    max_seg_ctx_chars: int | None = None,
    max_seg_ctx_trunc_dropped: int | None = None,
    max_plan_req_seg_chars_p90: int | None = None,
    max_plan_req_seg_trunc_dropped: int | None = None,
    plan_req_fallback_used: str = "any",
    min_plan_seg_ctx_coverage: float | None = None,
    min_plan_pov_ctx_coverage: float | None = None,
    min_plan_slam_ctx_coverage: float | None = None,
    require_plan_ctx_used: str = "any",
    require_plan_slam_ctx_used: str = "any",
    max_plan_ctx_trunc_rate: float | None = None,
    min_plan_ctx_chars_p90: int | None = None,
    require_slam_ctx_present: str = "any",
    max_slam_ctx_trunc_rate: float | None = None,
    min_slam_tracking_rate_mean: float | None = None,
    min_seg_prompt_text_chars: int | None = None,
    max_seg_prompt_trunc_rate: float | None = None,
    max_seg_prompt_trunc_dropped: int | None = None,
    has_pov: str = "any",
    min_pov_decisions: int | None = None,
    has_pov_context: str = "any",
    min_pov_context_token_approx: int | None = None,
    has_plan: str = "any",
    plan_fallback_used: str = "any",
    max_plan_latency_p90: int | None = None,
    max_plan_overcautious_rate: float | None = None,
    max_plan_guardrail_override_rate: float | None = None,
    require_plan_costmap_ctx_used: str = "any",
    max_plan_guardrails: int | None = None,
    min_plan_score: float | None = None,
    plan_risk_level: str | None = None,
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
        max_confirm_timeouts=max_confirm_timeouts,
        max_critical_misses=max_critical_misses,
        max_risk_latency_p90=max_risk_latency_p90,
        max_risk_latency_max=max_risk_latency_max,
        max_ocr_cer=max_ocr_cer,
        min_ocr_exact_match_rate=min_ocr_exact_match_rate,
        min_ocr_coverage=min_ocr_coverage,
        max_ocr_latency_p90=max_ocr_latency_p90,
        min_seg_f1_50=min_seg_f1_50,
        min_seg_coverage=min_seg_coverage,
        min_seg_track_coverage=min_seg_track_coverage,
        min_seg_tracks_total=min_seg_tracks_total,
        max_seg_id_switches=max_seg_id_switches,
        min_depth_delta1=min_depth_delta1,
        max_depth_absrel=max_depth_absrel,
        min_depth_coverage=min_depth_coverage,
        max_depth_latency_p90=max_depth_latency_p90,
        min_costmap_coverage=min_costmap_coverage,
        max_costmap_latency_p90=max_costmap_latency_p90,
        max_costmap_dynamic_filter_rate_mean=max_costmap_dynamic_filter_rate_mean,
        min_costmap_fused_coverage=min_costmap_fused_coverage,
        max_costmap_fused_latency_p90=max_costmap_fused_latency_p90,
        min_costmap_fused_iou_p90=min_costmap_fused_iou_p90,
        max_costmap_fused_flicker_rate_mean=max_costmap_fused_flicker_rate_mean,
        max_costmap_fused_shift_gate_reject_rate=max_costmap_fused_shift_gate_reject_rate,
        min_costmap_fused_shift_used_rate=min_costmap_fused_shift_used_rate,
        min_slam_tracking_rate=min_slam_tracking_rate,
        max_slam_lost_rate=max_slam_lost_rate,
        max_slam_latency_p90=max_slam_latency_p90,
        max_slam_align_residual_p90=max_slam_align_residual_p90,
        max_slam_ate_rmse=max_slam_ate_rmse,
        max_slam_rpe_trans_rmse=max_slam_rpe_trans_rmse,
        min_seg_mask_f1_50=min_seg_mask_f1_50,
        min_seg_mask_coverage=min_seg_mask_coverage,
        max_seg_latency_p90=max_seg_latency_p90,
        max_frame_e2e_p90=max_frame_e2e_p90,
        max_frame_e2e_max=max_frame_e2e_max,
        max_frame_user_e2e_p90=max_frame_user_e2e_p90,
        max_frame_user_e2e_max=max_frame_user_e2e_max,
        max_frame_user_e2e_tts_p90=max_frame_user_e2e_tts_p90,
        max_frame_user_e2e_ar_p90=max_frame_user_e2e_ar_p90,
        min_ack_kind_diversity=min_ack_kind_diversity,
        max_models_missing_required=max_models_missing_required,
        max_seg_ctx_chars=max_seg_ctx_chars,
        max_seg_ctx_trunc_dropped=max_seg_ctx_trunc_dropped,
        max_plan_req_seg_chars_p90=max_plan_req_seg_chars_p90,
        max_plan_req_seg_trunc_dropped=max_plan_req_seg_trunc_dropped,
        plan_req_fallback_used=plan_req_fallback_used,
        min_plan_seg_ctx_coverage=min_plan_seg_ctx_coverage,
        min_plan_pov_ctx_coverage=min_plan_pov_ctx_coverage,
        min_plan_slam_ctx_coverage=min_plan_slam_ctx_coverage,
        require_plan_ctx_used=require_plan_ctx_used,
        require_plan_slam_ctx_used=require_plan_slam_ctx_used,
        max_plan_ctx_trunc_rate=max_plan_ctx_trunc_rate,
        min_plan_ctx_chars_p90=min_plan_ctx_chars_p90,
        require_slam_ctx_present=require_slam_ctx_present,
        max_slam_ctx_trunc_rate=max_slam_ctx_trunc_rate,
        min_slam_tracking_rate_mean=min_slam_tracking_rate_mean,
        min_seg_prompt_text_chars=min_seg_prompt_text_chars,
        max_seg_prompt_trunc_rate=max_seg_prompt_trunc_rate,
        max_seg_prompt_trunc_dropped=max_seg_prompt_trunc_dropped,
        has_pov=has_pov,
        min_pov_decisions=min_pov_decisions,
        has_pov_context=has_pov_context,
        min_pov_context_token_approx=min_pov_context_token_approx,
        has_plan=has_plan,
        plan_fallback_used=plan_fallback_used,
        max_plan_latency_p90=max_plan_latency_p90,
        max_plan_overcautious_rate=max_plan_overcautious_rate,
        max_plan_guardrail_override_rate=max_plan_guardrail_override_rate,
        require_plan_costmap_ctx_used=require_plan_costmap_ctx_used,
        max_plan_guardrails=max_plan_guardrails,
        min_plan_score=min_plan_score,
        plan_risk_level=plan_risk_level,
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
        "confirm_timeouts",
        "missCriticalCount",
        "critical_misses",
        "max_delay_frames",
        "risk_latency_p90",
        "risk_latency_max",
        "ocr_cer",
        "ocr_exact_match_rate",
        "ocr_coverage",
        "ocr_latency_p90",
        "seg_f1_50",
        "seg_latency_p90",
        "seg_coverage",
        "seg_track_coverage",
        "seg_tracks_total",
        "seg_id_switches",
        "depth_absrel",
        "depth_rmse",
        "depth_delta1",
        "depth_coverage",
        "depth_latency_p90",
        "costmap_coverage",
        "costmap_latency_p90",
        "costmap_density_mean",
        "costmap_dynamic_filter_rate_mean",
        "costmap_fused_coverage",
        "costmap_fused_latency_p90",
        "costmap_fused_iou_p90",
        "costmap_fused_flicker_rate_mean",
        "costmap_fused_shift_used_rate",
        "costmap_fused_shift_gate_reject_rate",
        "slam_tracking_rate",
        "slam_lost_rate",
        "slam_latency_p90",
        "slam_align_residual_p90",
        "slam_align_mode",
        "slam_ate_rmse",
        "slam_rpe_trans_rmse",
        "frame_e2e_p90",
        "frame_e2e_max",
        "frame_seg_p90",
        "frame_risk_p90",
        "frame_plan_p90",
        "frame_execute_p90",
        "frame_user_e2e_p90",
        "frame_user_e2e_max",
        "frame_user_e2e_tts_p90",
        "frame_user_e2e_tts_max",
        "frame_user_e2e_ar_p90",
        "frame_user_e2e_ar_max",
        "ack_kind_diversity",
        "ack_coverage",
        "models_missing_required",
        "models_enabled_total",
        "seg_mask_f1_50",
        "seg_mask_coverage",
        "seg_mask_mean_iou",
        "seg_ctx_chars",
        "seg_ctx_segments",
        "seg_ctx_trunc_dropped",
        "plan_req_seg_chars_p90",
        "plan_req_seg_trunc_dropped",
        "plan_req_pov_chars_p90",
        "plan_req_fallback_used",
        "plan_rule_applied",
        "plan_rule_hint",
        "plan_ctx_used",
        "plan_ctx_used_rate",
        "plan_seg_ctx_coverage",
        "plan_pov_ctx_coverage",
        "plan_slam_ctx_coverage",
        "plan_slam_ctx_hit_rate",
        "plan_slam_ctx_used_rate",
        "plan_costmap_ctx_coverage_p90",
        "plan_costmap_ctx_used_rate",
        "plan_ctx_chars_p90",
        "plan_ctx_trunc_rate",
        "plan_ctx_seg_chars_p90",
        "plan_ctx_pov_chars_p90",
        "plan_ctx_risk_chars_p90",
        "slam_ctx_present",
        "slam_ctx_chars_p90",
        "slam_ctx_trunc_rate",
        "slam_tracking_rate_mean",
        "seg_prompt_present",
        "seg_prompt_text_chars_total",
        "seg_prompt_chars_out",
        "seg_prompt_targets_out",
        "seg_prompt_trunc_dropped",
        "seg_prompt_trunc_rate",
        "pov_present",
        "pov_decisions",
        "pov_duration_ms",
        "pov_token_approx",
        "pov_decision_per_min",
        "pov_context_token_approx",
        "pov_context_chars",
        "plan_present",
        "plan_risk_level",
        "plan_actions",
        "plan_guardrails",
        "plan_has_stop",
        "plan_has_confirm",
        "plan_score",
        "plan_fallback_used",
        "plan_json_valid",
        "plan_prompt_version",
        "plan_latency_p90",
        "confirm_requests",
        "plan_overcautious_rate",
        "plan_guardrail_override_rate",
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


def _load_run_package_manifest(run_package_dir: Path) -> tuple[Path, dict[str, Any]]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_package_dir / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"manifest parse failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="manifest must be object")
        return path, payload
    raise HTTPException(status_code=404, detail="manifest not found in run package")


def _find_package_dir_with_manifest(root: Path) -> Path:
    candidates = list(root.rglob("manifest.json")) + list(root.rglob("run_manifest.json"))
    if not candidates:
        raise HTTPException(status_code=404, detail="manifest not found in extracted run package")
    candidates.sort(key=lambda item: len(str(item)))
    return candidates[0].parent


def _resolve_context_run_package_input(run_package_raw: str) -> tuple[Path, Path | None, bool]:
    run_package_text = str(run_package_raw or "").strip()
    source_path = Path(run_package_text)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"runPackage not found: {run_package_text}")
    if source_path.is_dir():
        return source_path.resolve(), None, True
    if source_path.is_file() and source_path.suffix.lower() == ".zip":
        extract_root = Path(tempfile.mkdtemp(prefix="pov_context_extract_"))
        safe_extract_zip(source_path, extract_root)
        package_dir = extract_root
        try:
            load_run_package(package_dir)
        except Exception:
            package_dir = _find_package_dir_with_manifest(extract_root)
        return package_dir.resolve(), extract_root, False
    raise HTTPException(status_code=400, detail="runPackage must be directory or .zip")


async def _resolve_context_run_package_dir_async(
    *,
    run_package_raw: str | None,
    run_id: str | None,
) -> tuple[Path, Path | None, bool]:
    run_package_text = str(run_package_raw or "").strip()
    run_id_text = str(run_id or "").strip()
    if run_package_text:
        return _resolve_context_run_package_input(run_package_text)
    if not run_id_text:
        raise HTTPException(status_code=400, detail="runPackage or runId is required")
    entry = await gateway.get_run_package(run_id_text)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"runId not found: {run_id_text}")
    report_path = gateway._resolve_run_packages_path(str(entry.get("reportMdPath", "")))  # noqa: SLF001
    package_dir = report_path.parent
    if not package_dir.exists():
        raise HTTPException(status_code=404, detail=f"run package dir not found for runId: {run_id_text}")
    return package_dir.resolve(), None, True


def _load_pov_ir_for_context(run_package_dir: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    _manifest_path, manifest = _load_run_package_manifest(run_package_dir)
    pov_rel = str(manifest.get("povIrJson", "")).strip()
    if not pov_rel:
        raise HTTPException(status_code=404, detail="povIrJson missing in manifest")
    pov_path = run_package_dir / pov_rel
    if not pov_path.exists():
        raise HTTPException(status_code=404, detail=f"povIrJson not found: {pov_rel}")
    try:
        payload = json.loads(pov_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"povIrJson parse failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="povIrJson must be object")
    ok, errors = validate_pov_ir(payload, strict=True)
    if not ok:
        raise HTTPException(status_code=400, detail={"message": "pov ir schema invalid", "errors": errors})
    return manifest, payload, pov_path


def _try_append_pov_context_event(
    *,
    run_package_dir: Path,
    manifest: dict[str, Any],
    run_id: str,
    latency_ms: int,
    budget: dict[str, Any],
    out_stats: dict[str, Any],
    truncation: dict[str, Any],
) -> bool:
    events_rel = str(manifest.get("eventsV1Jsonl", "")).strip() or "events/events_v1.jsonl"
    events_path = run_package_dir / events_rel
    if not events_path.exists() or not events_path.is_file():
        return False
    payload = {
        "schemaVersion": "pov.context.v1",
        "budget": budget,
        "outStats": out_stats,
        "truncation": truncation,
    }
    event = {
        "schemaVersion": "byes.event.v1",
        "tsMs": _now_ms(),
        "runId": run_id,
        "frameSeq": 1,
        "component": "gateway",
        "category": "pov",
        "name": "pov.context",
        "phase": "result",
        "status": "ok",
        "latencyMs": int(max(0, latency_ms)),
        "payload": payload,
    }
    with events_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(event, ensure_ascii=False) + "\n")
    return True


def _resolve_events_v1_path(run_package_dir: Path, manifest: dict[str, Any]) -> Path:
    events_rel = str(manifest.get("eventsV1Jsonl", "")).strip() or "events/events_v1.jsonl"
    return run_package_dir / events_rel


_FRAME_E2E_STATE_LOCK = threading.Lock()
_FRAME_E2E_STATE: dict[tuple[str, str, int], dict[str, Any]] = {}
_FRAME_USER_E2E_STATE_LOCK = threading.Lock()
_FRAME_USER_E2E_STATE: dict[tuple[str, int], dict[str, Any]] = {}


def _frame_e2e_state_key(events_path: Path, run_id: str, frame_seq: int) -> tuple[str, str, int]:
    resolved = str(events_path.resolve()).lower()
    safe_run_id = str(run_id or "").strip()
    safe_frame_seq = int(max(1, int(frame_seq)))
    return (resolved, safe_run_id, safe_frame_seq)


def _frame_user_e2e_state_key(run_id: str, frame_seq: int) -> tuple[str, int]:
    return (str(run_id or "").strip() or "unknown-run", int(max(1, int(frame_seq))))


def _frame_user_e2e_mark_input(run_id: str, frame_seq: int, t0_ms: int | None) -> None:
    key = _frame_user_e2e_state_key(run_id, frame_seq)
    t0_value = _to_nonnegative_int_or_none(t0_ms)
    with _FRAME_USER_E2E_STATE_LOCK:
        state = _FRAME_USER_E2E_STATE.get(key)
        if not isinstance(state, dict):
            state = {"t0Ms": t0_value, "feedbackTsMs": None, "accepted": True, "emitted": False}
            _FRAME_USER_E2E_STATE[key] = state
            return
        current_t0 = _to_nonnegative_int_or_none(state.get("t0Ms"))
        if t0_value is not None and (current_t0 is None or t0_value < current_t0):
            state["t0Ms"] = int(t0_value)


def _frame_user_e2e_mark_ack(run_id: str, frame_seq: int, feedback_ts_ms: int, accepted: bool) -> None:
    key = _frame_user_e2e_state_key(run_id, frame_seq)
    feedback_value = _to_nonnegative_int_or_none(feedback_ts_ms)
    with _FRAME_USER_E2E_STATE_LOCK:
        state = _FRAME_USER_E2E_STATE.get(key)
        if not isinstance(state, dict):
            state = {"t0Ms": None, "feedbackTsMs": feedback_value, "accepted": bool(accepted), "emitted": False}
            _FRAME_USER_E2E_STATE[key] = state
            return
        if feedback_value is not None:
            state["feedbackTsMs"] = int(feedback_value)
        state["accepted"] = bool(accepted)


def _frame_user_e2e_snapshot(run_id: str, frame_seq: int) -> dict[str, Any] | None:
    key = _frame_user_e2e_state_key(run_id, frame_seq)
    with _FRAME_USER_E2E_STATE_LOCK:
        state = _FRAME_USER_E2E_STATE.get(key)
        if not isinstance(state, dict):
            return None
        return {
            "t0Ms": _to_nonnegative_int_or_none(state.get("t0Ms")),
            "feedbackTsMs": _to_nonnegative_int_or_none(state.get("feedbackTsMs")),
            "accepted": bool(state.get("accepted", True)),
            "emitted": bool(state.get("emitted", False)),
        }


def _frame_user_e2e_mark_emitted(run_id: str, frame_seq: int) -> None:
    key = _frame_user_e2e_state_key(run_id, frame_seq)
    with _FRAME_USER_E2E_STATE_LOCK:
        state = _FRAME_USER_E2E_STATE.get(key)
        if isinstance(state, dict):
            state["emitted"] = True


def _frame_user_e2e_exists_in_rows(rows: list[dict[str, Any]], *, run_id: str, frame_seq: int) -> bool:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("name", "")).strip().lower() != "frame.user_e2e":
            continue
        if str(row.get("runId", "")).strip() != str(run_id or "").strip():
            continue
        if _to_nonnegative_int(row.get("frameSeq"), 0) != int(max(1, int(frame_seq))):
            continue
        return True
    return False


def _frame_e2e_begin_state(
    *,
    events_path: Path,
    run_id: str,
    frame_seq: int,
    t0_hint_ms: int | None = None,
) -> None:
    key = _frame_e2e_state_key(events_path, run_id, frame_seq)
    t0_hint = _to_nonnegative_int_or_none(t0_hint_ms)
    with _FRAME_E2E_STATE_LOCK:
        state = _FRAME_E2E_STATE.get(key)
        if not isinstance(state, dict):
            state = {
                "t0Ms": t0_hint,
                "partsMs": {
                    "segMs": None,
                    "riskMs": None,
                    "planMs": None,
                    "executeMs": None,
                    "confirmMs": None,
                },
                "present": {
                    "seg": False,
                    "risk": False,
                    "plan": False,
                    "execute": False,
                    "confirm": False,
                },
                "emitted": False,
            }
            _FRAME_E2E_STATE[key] = state
            return
        if t0_hint is not None:
            current_t0 = _to_nonnegative_int_or_none(state.get("t0Ms"))
            if current_t0 is None:
                state["t0Ms"] = t0_hint
            else:
                state["t0Ms"] = int(min(current_t0, t0_hint))


def _frame_e2e_update_state(
    *,
    events_path: Path,
    run_id: str,
    frame_seq: int,
    t0_hint_ms: int | None = None,
    seg_ms: int | None = None,
    risk_ms: int | None = None,
    plan_ms: int | None = None,
    execute_ms: int | None = None,
    confirm_ms: int | None = None,
    seg_present: bool | None = None,
    risk_present: bool | None = None,
    plan_present: bool | None = None,
    execute_present: bool | None = None,
    confirm_present: bool | None = None,
) -> None:
    _frame_e2e_begin_state(
        events_path=events_path,
        run_id=run_id,
        frame_seq=frame_seq,
        t0_hint_ms=t0_hint_ms,
    )
    key = _frame_e2e_state_key(events_path, run_id, frame_seq)
    with _FRAME_E2E_STATE_LOCK:
        state = _FRAME_E2E_STATE.get(key)
        if not isinstance(state, dict):
            return
        parts = state.get("partsMs")
        if not isinstance(parts, dict):
            parts = {}
            state["partsMs"] = parts
        present = state.get("present")
        if not isinstance(present, dict):
            present = {}
            state["present"] = present
        for key_name, raw_value in (
            ("segMs", seg_ms),
            ("riskMs", risk_ms),
            ("planMs", plan_ms),
            ("executeMs", execute_ms),
            ("confirmMs", confirm_ms),
        ):
            value = _to_nonnegative_int_or_none(raw_value)
            if value is not None:
                parts[key_name] = int(value)
        for key_name, raw_value in (
            ("seg", seg_present),
            ("risk", risk_present),
            ("plan", plan_present),
            ("execute", execute_present),
            ("confirm", confirm_present),
        ):
            if raw_value is None:
                continue
            present[key_name] = bool(present.get(key_name, False) or bool(raw_value))


def _frame_e2e_state_snapshot(events_path: Path, run_id: str, frame_seq: int) -> dict[str, Any] | None:
    key = _frame_e2e_state_key(events_path, run_id, frame_seq)
    with _FRAME_E2E_STATE_LOCK:
        state = _FRAME_E2E_STATE.get(key)
        if not isinstance(state, dict):
            return None
        payload = {
            "t0Ms": _to_nonnegative_int_or_none(state.get("t0Ms")),
            "partsMs": {},
            "present": {},
            "emitted": bool(state.get("emitted")),
        }
        parts = state.get("partsMs")
        parts = parts if isinstance(parts, dict) else {}
        for key_name in ("segMs", "riskMs", "planMs", "executeMs", "confirmMs"):
            payload["partsMs"][key_name] = _to_nonnegative_int_or_none(parts.get(key_name))
        present = state.get("present")
        present = present if isinstance(present, dict) else {}
        for key_name in ("seg", "risk", "plan", "execute", "confirm"):
            payload["present"][key_name] = bool(present.get(key_name, False))
        return payload


def _frame_e2e_mark_emitted(events_path: Path, run_id: str, frame_seq: int) -> None:
    key = _frame_e2e_state_key(events_path, run_id, frame_seq)
    with _FRAME_E2E_STATE_LOCK:
        state = _FRAME_E2E_STATE.get(key)
        if isinstance(state, dict):
            state["emitted"] = True


def _frame_e2e_already_emitted(events_path: Path, run_id: str, frame_seq: int) -> bool:
    snapshot = _frame_e2e_state_snapshot(events_path, run_id, frame_seq)
    return bool(snapshot and snapshot.get("emitted"))


def _frame_e2e_exists_in_rows(rows: list[dict[str, Any]], *, run_id: str, frame_seq: int) -> bool:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("name", "")).strip().lower() != "frame.e2e":
            continue
        if str(row.get("runId", "")).strip() != str(run_id or "").strip():
            continue
        if _to_nonnegative_int(row.get("frameSeq"), 0) != int(max(1, int(frame_seq))):
            continue
        return True
    return False


def _append_events_v1_rows(events_path: Path, rows: list[dict[str, Any]]) -> bool:
    if not events_path.exists() or not events_path.is_file():
        return False
    with events_path.open("a", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def _to_nonnegative_int_or_none(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        parsed = int(float(value))
    except Exception:
        return None
    if parsed < 0:
        return None
    return parsed


def _to_nonnegative_int(value: Any, default: int = 0) -> int:
    parsed = _to_nonnegative_int_or_none(value)
    if parsed is None:
        return int(default)
    return int(parsed)


def _collect_frame_rows(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    frame_seq: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("runId", "")).strip() != run_id:
            continue
        if _to_nonnegative_int(row.get("frameSeq"), 0) != frame_seq:
            continue
        out.append(row)
    return out


def _read_events_v1_rows(events_path: Path) -> list[dict[str, Any]]:
    if not events_path.exists() or not events_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _latest_event_latency_ms(
    rows: list[dict[str, Any]],
    *,
    event_name: str,
    fallback_payload_path: list[str] | None = None,
) -> int | None:
    latest_ts = -1
    value: int | None = None
    for row in rows:
        if str(row.get("name", "")).strip().lower() != event_name:
            continue
        if str(row.get("phase", "")).strip().lower() != "result":
            continue
        if str(row.get("status", "")).strip().lower() != "ok":
            continue
        ts_ms = _to_nonnegative_int(row.get("tsMs"), 0)
        latency = _to_nonnegative_int_or_none(row.get("latencyMs"))
        if latency is None and fallback_payload_path:
            payload = row.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            current: Any = payload
            for key in fallback_payload_path:
                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    current = None
                if current is None:
                    break
            latency = _to_nonnegative_int_or_none(current)
        if ts_ms >= latest_ts:
            latest_ts = ts_ms
            value = latency
    return value


def _build_frame_input_payload(
    *,
    run_id: str,
    frame_seq: int,
    capture_ts_ms: int | None,
    recv_ts_ms: int,
    device_time_base: str | None,
    device_id: str | None,
) -> dict[str, Any]:
    normalized_time_base = str(device_time_base or "").strip().lower()
    if normalized_time_base not in {"unix_ms", "monotonic_ms"}:
        normalized_time_base = None
    normalized_device_id = str(device_id or "").strip() or None
    return {
        "schemaVersion": "frame.input.v1",
        "runId": str(run_id or "").strip() or "unknown-run",
        "frameSeq": int(max(1, int(frame_seq))),
        "captureTsMs": _to_nonnegative_int_or_none(capture_ts_ms),
        "recvTsMs": int(max(0, int(recv_ts_ms))),
        "meta": {
            "deviceTimeBase": normalized_time_base,
            "deviceId": normalized_device_id,
        },
    }


def _build_frame_ack_payload(
    *,
    run_id: str,
    frame_seq: int,
    feedback_ts_ms: int,
    kind: str,
    accepted: bool,
) -> dict[str, Any]:
    normalized_kind = str(kind or "any").strip().lower()
    if normalized_kind == "ar":
        normalized_kind = "overlay"
    elif normalized_kind == "other":
        normalized_kind = "any"
    if normalized_kind not in {"tts", "overlay", "haptic", "any"}:
        normalized_kind = "any"
    return {
        "schemaVersion": "frame.ack.v1",
        "runId": str(run_id or "").strip() or "unknown-run",
        "frameSeq": int(max(1, int(frame_seq))),
        "feedbackTsMs": int(max(0, int(feedback_ts_ms))),
        "kind": normalized_kind,
        "accepted": bool(accepted),
    }


def _build_frame_user_e2e_event(
    *,
    run_id: str,
    frame_seq: int,
    t0_ms: int,
    feedback_ts_ms: int,
) -> dict[str, Any]:
    safe_t0 = int(max(0, int(t0_ms)))
    safe_feedback = int(max(0, int(feedback_ts_ms)))
    safe_t1 = int(max(safe_t0, safe_feedback))
    total_ms = int(max(0, safe_t1 - safe_t0))
    payload = {
        "schemaVersion": "frame.e2e.v1",
        "runId": str(run_id or "").strip() or "unknown-run",
        "frameSeq": int(max(1, int(frame_seq))),
        "t0Ms": safe_t0,
        "t1Ms": safe_t1,
        "totalMs": total_ms,
        "partsMs": {
            "segMs": None,
            "riskMs": None,
            "planMs": None,
            "executeMs": None,
            "confirmMs": None,
        },
        "present": {
            "seg": False,
            "risk": False,
            "plan": False,
            "execute": False,
            "confirm": False,
        },
    }
    return _build_byes_event(
        run_id=str(run_id or "").strip() or "unknown-run",
        frame_seq=int(max(1, int(frame_seq))),
        category="frame",
        name="frame.user_e2e",
        latency_ms=total_ms,
        payload=payload,
    )


def _try_append_frame_user_e2e_event(
    *,
    events_path: Path,
    run_id: str,
    frame_seq: int,
) -> bool:
    safe_frame_seq = int(max(1, int(frame_seq)))
    snapshot = _frame_user_e2e_snapshot(run_id, safe_frame_seq)
    if not isinstance(snapshot, dict):
        return False
    if bool(snapshot.get("emitted")):
        return True
    t0_ms = _to_nonnegative_int_or_none(snapshot.get("t0Ms"))
    feedback_ts_ms = _to_nonnegative_int_or_none(snapshot.get("feedbackTsMs"))
    if t0_ms is None or feedback_ts_ms is None:
        return False
    existing = _read_events_v1_rows(events_path)
    if _frame_user_e2e_exists_in_rows(existing, run_id=run_id, frame_seq=safe_frame_seq):
        _frame_user_e2e_mark_emitted(run_id, safe_frame_seq)
        return True
    row = _build_frame_user_e2e_event(
        run_id=run_id,
        frame_seq=safe_frame_seq,
        t0_ms=t0_ms,
        feedback_ts_ms=feedback_ts_ms,
    )
    ok = _append_events_v1_rows(events_path, [row])
    if ok:
        _frame_user_e2e_mark_emitted(run_id, safe_frame_seq)
    return ok


def _build_frame_e2e_payload(
    *,
    rows: list[dict[str, Any]],
    run_id: str,
    frame_seq: int,
    t1_ms: int,
    t0_hint_ms: int | None = None,
    state_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frame_rows = _collect_frame_rows(rows, run_id=run_id, frame_seq=frame_seq)
    non_e2e_rows = [
        row
        for row in frame_rows
        if str(row.get("name", "")).strip().lower() != "frame.e2e"
    ]
    ts_candidates = [
        _to_nonnegative_int(row.get("tsMs"), 0)
        for row in non_e2e_rows
        if _to_nonnegative_int_or_none(row.get("tsMs")) is not None
    ]
    fallback_t0 = _to_nonnegative_int_or_none(t0_hint_ms)
    state = state_snapshot if isinstance(state_snapshot, dict) else {}
    state_t0 = _to_nonnegative_int_or_none(state.get("t0Ms"))
    t0_ms = min(ts_candidates) if ts_candidates else (fallback_t0 if fallback_t0 is not None else int(max(0, t1_ms)))
    if state_t0 is not None:
        t0_ms = min(int(max(0, t0_ms)), int(max(0, state_t0)))
    safe_t1 = max(int(max(0, t1_ms)), int(max(0, t0_ms)))

    seg_present = any(str(row.get("name", "")).strip().lower() == "seg.segment" for row in non_e2e_rows)
    risk_present = any(str(row.get("name", "")).strip().lower() == "risk.hazards" for row in non_e2e_rows)
    plan_present = any(str(row.get("name", "")).strip().lower() == "plan.generate" for row in non_e2e_rows)
    execute_present = any(str(row.get("name", "")).strip().lower() == "plan.execute" for row in non_e2e_rows)
    confirm_present = any(str(row.get("name", "")).strip().lower() == "ui.confirm_response" for row in non_e2e_rows)

    seg_ms = _latest_event_latency_ms(non_e2e_rows, event_name="seg.segment")
    risk_ms = _latest_event_latency_ms(
        non_e2e_rows,
        event_name="risk.hazards",
        fallback_payload_path=["debug", "timings", "totalMs"],
    )
    plan_ms = _latest_event_latency_ms(non_e2e_rows, event_name="plan.generate")
    execute_ms = _latest_event_latency_ms(non_e2e_rows, event_name="plan.execute")
    confirm_ms = _latest_event_latency_ms(
        non_e2e_rows,
        event_name="ui.confirm_response",
        fallback_payload_path=["latencyMs"],
    )
    state_parts = state.get("partsMs")
    state_parts = state_parts if isinstance(state_parts, dict) else {}
    state_present = state.get("present")
    state_present = state_present if isinstance(state_present, dict) else {}
    seg_ms = _to_nonnegative_int_or_none(state_parts.get("segMs")) if _to_nonnegative_int_or_none(state_parts.get("segMs")) is not None else seg_ms
    risk_ms = _to_nonnegative_int_or_none(state_parts.get("riskMs")) if _to_nonnegative_int_or_none(state_parts.get("riskMs")) is not None else risk_ms
    plan_ms = _to_nonnegative_int_or_none(state_parts.get("planMs")) if _to_nonnegative_int_or_none(state_parts.get("planMs")) is not None else plan_ms
    execute_ms = (
        _to_nonnegative_int_or_none(state_parts.get("executeMs"))
        if _to_nonnegative_int_or_none(state_parts.get("executeMs")) is not None
        else execute_ms
    )
    confirm_ms = (
        _to_nonnegative_int_or_none(state_parts.get("confirmMs"))
        if _to_nonnegative_int_or_none(state_parts.get("confirmMs")) is not None
        else confirm_ms
    )
    seg_present = bool(seg_present or bool(state_present.get("seg")))
    risk_present = bool(risk_present or bool(state_present.get("risk")))
    plan_present = bool(plan_present or bool(state_present.get("plan")))
    execute_present = bool(execute_present or bool(state_present.get("execute")))
    confirm_present = bool(confirm_present or bool(state_present.get("confirm")))

    return {
        "schemaVersion": "frame.e2e.v1",
        "runId": run_id,
        "frameSeq": int(max(1, frame_seq)),
        "t0Ms": int(max(0, t0_ms)),
        "t1Ms": int(max(0, safe_t1)),
        "totalMs": int(max(0, safe_t1 - int(max(0, t0_ms)))),
        "partsMs": {
            "segMs": seg_ms,
            "riskMs": risk_ms,
            "planMs": plan_ms,
            "executeMs": execute_ms,
            "confirmMs": confirm_ms,
        },
        "present": {
            "seg": bool(seg_present),
            "risk": bool(risk_present),
            "plan": bool(plan_present),
            "execute": bool(execute_present),
            "confirm": bool(confirm_present),
        },
    }


def _build_frame_e2e_event(
    *,
    rows: list[dict[str, Any]],
    run_id: str,
    frame_seq: int,
    t1_ms: int,
    t0_hint_ms: int | None = None,
    state_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _build_frame_e2e_payload(
        rows=rows,
        run_id=run_id,
        frame_seq=frame_seq,
        t1_ms=t1_ms,
        t0_hint_ms=t0_hint_ms,
        state_snapshot=state_snapshot,
    )
    return _build_byes_event(
        run_id=run_id,
        frame_seq=frame_seq,
        category="frame",
        name="frame.e2e",
        latency_ms=int(max(0, _to_nonnegative_int(payload.get("totalMs"), 0))),
        payload=payload,
    )


def _try_append_frame_e2e_event(
    *,
    events_path: Path,
    run_id: str,
    frame_seq: int,
    t1_ms: int,
    t0_hint_ms: int | None = None,
    seg_ms: int | None = None,
    risk_ms: int | None = None,
    plan_ms: int | None = None,
    execute_ms: int | None = None,
    confirm_ms: int | None = None,
    seg_present: bool | None = None,
    risk_present: bool | None = None,
    plan_present: bool | None = None,
    execute_present: bool | None = None,
    confirm_present: bool | None = None,
) -> bool:
    safe_frame_seq = int(max(1, int(frame_seq)))
    _frame_e2e_update_state(
        events_path=events_path,
        run_id=run_id,
        frame_seq=safe_frame_seq,
        t0_hint_ms=t0_hint_ms,
        seg_ms=seg_ms,
        risk_ms=risk_ms,
        plan_ms=plan_ms,
        execute_ms=execute_ms,
        confirm_ms=confirm_ms,
        seg_present=seg_present,
        risk_present=risk_present,
        plan_present=plan_present,
        execute_present=execute_present,
        confirm_present=confirm_present,
    )
    if _frame_e2e_already_emitted(events_path, run_id, safe_frame_seq):
        return True
    existing = _read_events_v1_rows(events_path)
    if _frame_e2e_exists_in_rows(existing, run_id=run_id, frame_seq=safe_frame_seq):
        _frame_e2e_mark_emitted(events_path, run_id, safe_frame_seq)
        return True
    state_snapshot = _frame_e2e_state_snapshot(events_path, run_id, safe_frame_seq)
    row = _build_frame_e2e_event(
        rows=existing,
        run_id=run_id,
        frame_seq=safe_frame_seq,
        t1_ms=t1_ms,
        t0_hint_ms=t0_hint_ms,
        state_snapshot=state_snapshot,
    )
    ok = _append_events_v1_rows(events_path, [row])
    if ok:
        _frame_e2e_mark_emitted(events_path, run_id, safe_frame_seq)
    return ok


def _build_plan_request_event_payload(plan_request: dict[str, Any] | None, planner: dict[str, Any]) -> dict[str, Any]:
    request_payload = plan_request if isinstance(plan_request, dict) else {}
    contexts = request_payload.get("contexts")
    contexts = contexts if isinstance(contexts, dict) else {}
    seg = contexts.get("seg")
    seg = seg if isinstance(seg, dict) else {}
    pov = contexts.get("pov")
    pov = pov if isinstance(pov, dict) else {}
    slam = contexts.get("slam")
    slam = slam if isinstance(slam, dict) else {}
    costmap = contexts.get("costmap")
    costmap = costmap if isinstance(costmap, dict) else {}
    seg_trunc = seg.get("truncation")
    seg_trunc = seg_trunc if isinstance(seg_trunc, dict) else {}
    meta = request_payload.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    seg_chars = int(seg.get("chars", 0) or 0)
    pov_chars = int(pov.get("chars", 0) or 0)
    slam_chars = int(slam.get("chars", meta.get("slamChars", 0)) or 0)
    costmap_chars = int(costmap.get("chars", meta.get("costmapChars", 0)) or 0)
    slam_included_raw = slam.get("present")
    if not isinstance(slam_included_raw, bool):
        slam_included_raw = meta.get("slamIncluded")
    costmap_included_raw = costmap.get("present")
    if not isinstance(costmap_included_raw, bool):
        costmap_included_raw = meta.get("costmapIncluded")
    return {
        "schemaVersion": "byes.plan_request.v1",
        "provider": planner.get("plannerProvider") or planner.get("provider") or meta.get("provider"),
        "promptVersion": planner.get("promptVersion") or meta.get("promptVersion"),
        "segIncluded": bool(seg.get("included")),
        "povIncluded": bool(pov.get("included")),
        "slamIncluded": bool(slam_included_raw) if isinstance(slam_included_raw, bool) else bool(slam.get("promptFragment")),
        "costmapIncluded": bool(costmap_included_raw)
        if isinstance(costmap_included_raw, bool)
        else bool(costmap.get("promptFragment")),
        "segChars": int(max(0, seg_chars)),
        "povChars": int(max(0, pov_chars)),
        "slamChars": int(max(0, slam_chars)),
        "costmapChars": int(max(0, costmap_chars)),
        "segTruncSegmentsDropped": int(max(0, int(seg_trunc.get("segmentsDropped", 0) or 0))),
        "segTruncCharsDropped": int(max(0, int(seg_trunc.get("charsDropped", 0) or 0))),
        "fallbackUsed": bool(planner.get("fallbackUsed")) if isinstance(planner.get("fallbackUsed"), bool) else None,
        "fallbackReason": planner.get("fallbackReason"),
    }


def _build_plan_context_alignment_event_payload(
    alignment_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    def _nn_int(raw: Any) -> int:
        try:
            if raw is None or isinstance(raw, bool):
                return 0
            return max(0, int(float(raw)))
        except Exception:
            return 0

    def _unit_float(raw: Any) -> float:
        try:
            if raw is None or isinstance(raw, bool):
                return 0.0
            parsed = float(raw)
        except Exception:
            return 0.0
        if parsed < 0.0:
            return 0.0
        if parsed > 1.0:
            return 1.0
        return parsed

    payload = alignment_payload if isinstance(alignment_payload, dict) else {}
    seg = payload.get("seg")
    seg = seg if isinstance(seg, dict) else {}
    pov = payload.get("pov")
    pov = pov if isinstance(pov, dict) else {}
    slam = payload.get("slam")
    slam = slam if isinstance(slam, dict) else {}
    costmap = payload.get("costmap")
    costmap = costmap if isinstance(costmap, dict) else {}
    detail = payload.get("contextUsedDetail")
    detail = detail if isinstance(detail, dict) else {}
    matched_raw = seg.get("matched")
    matched = [str(item) for item in matched_raw[:5]] if isinstance(matched_raw, list) else []
    slam_matched_raw = slam.get("matched")
    slam_matched = [str(item) for item in slam_matched_raw[:5]] if isinstance(slam_matched_raw, list) else []
    costmap_matched_raw = costmap.get("matched")
    costmap_matched = [str(item) for item in costmap_matched_raw[:5]] if isinstance(costmap_matched_raw, list) else []
    return {
        "schemaVersion": "plan.context_alignment.v1",
        "seg": {
            "present": bool(seg.get("present")),
            "labelCount": _nn_int(seg.get("labelCount")),
            "hit": bool(seg.get("hit")),
            "coverage": _unit_float(seg.get("coverage")),
            "matched": matched,
        },
        "pov": {
            "present": bool(pov.get("present")),
            "tokenCount": _nn_int(pov.get("tokenCount")),
            "hit": bool(pov.get("hit")),
            "coverage": _unit_float(pov.get("coverage")),
            "hitCount": _nn_int(pov.get("hitCount")),
        },
        "slam": {
            "present": bool(slam.get("present")),
            "hit": bool(slam.get("hit")),
            "coverage": _unit_float(slam.get("coverage")),
            "planTextChars": _nn_int(slam.get("planTextChars")),
            "matched": slam_matched,
        },
        "costmap": {
            "present": bool(costmap.get("present")),
            "hit": bool(costmap.get("hit")),
            "coverage": _unit_float(costmap.get("coverage")),
            "planTextChars": _nn_int(costmap.get("planTextChars")),
            "matched": costmap_matched,
        },
        "contextUsed": bool(payload.get("contextUsed")),
        "contextUsedDetail": {
            "seg": bool(detail.get("seg")),
            "pov": bool(detail.get("pov")),
            "slam": bool(detail.get("slam")),
            "costmap": bool(detail.get("costmap")),
        },
    }


def _build_plan_context_pack_event_payload(
    plan_context_pack: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = plan_context_pack if isinstance(plan_context_pack, dict) else {}
    budget = payload.get("budget")
    budget = budget if isinstance(budget, dict) else {}
    stats = payload.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    out_stats = stats.get("out")
    out_stats = out_stats if isinstance(out_stats, dict) else {}
    truncation = stats.get("truncation")
    truncation = truncation if isinstance(truncation, dict) else {}
    text = payload.get("text")
    text = text if isinstance(text, dict) else {}
    parts = payload.get("parts")
    parts = parts if isinstance(parts, dict) else {}
    run_id_value = str(payload.get("runId", "")).strip() or "plan-context-pack"
    return {
        "schemaVersion": "plan.context_pack.v1",
        "runId": run_id_value,
        "budget": {
            "maxChars": int(max(0, int(budget.get("maxChars", 0) or 0))),
            "mode": str(budget.get("mode", "")).strip() or None,
        },
        "parts": {
            "seg": parts.get("seg"),
            "pov": parts.get("pov"),
            "risk": parts.get("risk"),
        },
        "stats": {
            "out": {
                "charsTotal": int(max(0, int(out_stats.get("charsTotal", 0) or 0))),
                "tokenApprox": int(max(0, int(out_stats.get("tokenApprox", 0) or 0))),
                "segChars": int(max(0, int(out_stats.get("segChars", 0) or 0))),
                "povChars": int(max(0, int(out_stats.get("povChars", 0) or 0))),
                "riskChars": int(max(0, int(out_stats.get("riskChars", 0) or 0))),
            },
            "truncation": {
                "charsDropped": int(max(0, int(truncation.get("charsDropped", 0) or 0))),
                "segCharsDropped": int(max(0, int(truncation.get("segCharsDropped", 0) or 0))),
                "povCharsDropped": int(max(0, int(truncation.get("povCharsDropped", 0) or 0))),
                "riskCharsDropped": int(max(0, int(truncation.get("riskCharsDropped", 0) or 0))),
            },
        },
        "text": {
            "summary": str(text.get("summary", "") or ""),
            "prompt": str(text.get("prompt", "") or ""),
        },
    }


def _try_append_plan_events(
    *,
    run_package_dir: Path,
    manifest: dict[str, Any],
    run_id: str,
    frame_seq: int | None,
    latency_ms: int,
    planner: dict[str, Any],
    risk_level: str,
    actions_count: int,
    stop_count: int,
    confirm_action_count: int,
    blocking_count: int,
    guardrails_applied: list[str],
    findings_count: int,
    plan_request: dict[str, Any] | None = None,
    rule_payload: dict[str, Any] | None = None,
    alignment_payload: dict[str, Any] | None = None,
    plan_context_pack: dict[str, Any] | None = None,
    t0_hint_ms: int | None = None,
) -> bool:
    events_path = _resolve_events_v1_path(run_package_dir, manifest)
    _frame_e2e_update_state(
        events_path=events_path,
        run_id=run_id,
        frame_seq=int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1,
        t0_hint_ms=t0_hint_ms,
        plan_ms=latency_ms,
        plan_present=True,
    )
    now_ms = _now_ms()
    safe_frame_seq = int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1
    planner_payload = {
        "backend": planner.get("backend"),
        "model": planner.get("model"),
        "endpoint": planner.get("endpoint"),
        "plannerProvider": planner.get("plannerProvider") or planner.get("provider"),
        "promptVersion": planner.get("promptVersion"),
        "fallbackUsed": planner.get("fallbackUsed"),
        "fallbackReason": planner.get("fallbackReason"),
        "jsonValid": planner.get("jsonValid"),
        "contextUsedDetail": planner.get("contextUsedDetail"),
        "riskLevel": str(risk_level or "low"),
        "actionsCount": int(max(0, actions_count)),
        "stopCount": int(max(0, stop_count)),
        "confirmActionCount": int(max(0, confirm_action_count)),
        "blockingCount": int(max(0, blocking_count)),
    }
    safety_payload = {
        "riskLevel": str(risk_level or "low"),
        "guardrailsApplied": [str(item) for item in guardrails_applied if str(item).strip()],
        "findingsCount": int(max(0, findings_count)),
    }
    plan_request_payload = _build_plan_request_event_payload(plan_request, planner)
    alignment = _build_plan_context_alignment_event_payload(alignment_payload)
    plan_context_pack_payload = _build_plan_context_pack_event_payload(plan_context_pack)
    rows = [
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": now_ms,
            "runId": run_id,
            "frameSeq": safe_frame_seq,
            "component": "gateway",
            "category": "plan",
            "name": "plan.context_pack",
            "phase": "result",
            "status": "ok",
            "latencyMs": int(max(0, latency_ms)),
            "payload": plan_context_pack_payload,
        },
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": now_ms,
            "runId": run_id,
            "frameSeq": safe_frame_seq,
            "component": "gateway",
            "category": "plan",
            "name": "plan.request",
            "phase": "result",
            "status": "ok",
            "latencyMs": int(max(0, latency_ms)),
            "payload": plan_request_payload,
        },
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": now_ms,
            "runId": run_id,
            "frameSeq": safe_frame_seq,
            "component": "gateway",
            "category": "plan",
            "name": "plan.context_alignment",
            "phase": "result",
            "status": "ok",
            "latencyMs": int(max(0, latency_ms)),
            "payload": alignment,
        },
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": now_ms,
            "runId": run_id,
            "frameSeq": safe_frame_seq,
            "component": "gateway",
            "category": "plan",
            "name": "plan.generate",
            "phase": "result",
            "status": "ok",
            "latencyMs": int(max(0, latency_ms)),
            "payload": planner_payload,
        },
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": now_ms,
            "runId": run_id,
            "frameSeq": safe_frame_seq,
            "component": "gateway",
            "category": "safety",
            "name": "safety.kernel",
            "phase": "result",
            "status": "ok",
            "latencyMs": int(max(0, latency_ms)),
            "payload": safety_payload,
        },
    ]
    rule = rule_payload if isinstance(rule_payload, dict) else {}
    if bool(rule.get("applied")):
        rows.append(
            {
                "schemaVersion": "byes.event.v1",
                "tsMs": now_ms,
                "runId": run_id,
                "frameSeq": safe_frame_seq,
                "component": "gateway",
                "category": "plan",
                "name": "plan.rule_applied",
                "phase": "result",
                "status": "ok",
                "latencyMs": int(max(0, latency_ms)),
                "payload": {
                    "ruleVersion": str(rule.get("ruleVersion", "v1")),
                    "hazardHint": rule.get("hazardHint"),
                    "matchedKeywords": [str(item) for item in (rule.get("matchedKeywords") or [])[:3]],
                    "segContextUsed": bool(rule.get("segContextUsed")),
                    "riskLevel": rule.get("riskLevel"),
                },
            }
        )
    if not _append_events_v1_rows(events_path, rows):
        return False
    return True


def _try_append_plan_execute_event(
    *,
    run_package_dir: Path,
    manifest: dict[str, Any],
    run_id: str,
    frame_seq: int | None,
    latency_ms: int,
    executed_count: int,
    blocked_count: int,
    pending_confirm_count: int,
    ui_events: list[dict[str, Any]],
    t0_hint_ms: int | None = None,
) -> bool:
    events_path = _resolve_events_v1_path(run_package_dir, manifest)
    _frame_e2e_update_state(
        events_path=events_path,
        run_id=run_id,
        frame_seq=int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1,
        t0_hint_ms=t0_hint_ms,
        execute_ms=latency_ms,
        execute_present=True,
    )
    safe_frame_seq = int(frame_seq) if isinstance(frame_seq, int) and frame_seq > 0 else 1
    rows: list[dict[str, Any]] = [
        _build_byes_event(
            run_id=run_id,
            frame_seq=safe_frame_seq,
            category="plan",
            name="plan.execute",
            latency_ms=int(max(0, latency_ms)),
            payload={
                "executedCount": int(max(0, executed_count)),
                "blockedCount": int(max(0, blocked_count)),
                "pendingConfirmCount": int(max(0, pending_confirm_count)),
            },
        )
    ]
    for ui_event in ui_events:
        event_name = str(ui_event.get("name", "")).strip().lower()
        if event_name == "ui.command":
            rows.append(
                _build_byes_event(
                    run_id=run_id,
                    frame_seq=safe_frame_seq,
                    category="ui",
                    name="ui.command",
                    payload=ui_event.get("payload", {}),
                )
            )
        elif event_name == "ui.confirm_request":
            rows.append(
                _build_byes_event(
                    run_id=run_id,
                    frame_seq=safe_frame_seq,
                    category="ui",
                    name="ui.confirm_request",
                    payload=ui_event.get("payload", {}),
                    phase="start",
                )
            )
    if not _append_events_v1_rows(events_path, rows):
        return False
    return True


def _build_byes_event(
    *,
    run_id: str,
    frame_seq: int,
    category: str,
    name: str,
    payload: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    phase: str = "result",
) -> dict[str, Any]:
    return {
        "schemaVersion": "byes.event.v1",
        "tsMs": _now_ms(),
        "runId": run_id,
        "frameSeq": int(max(1, frame_seq)),
        "component": "gateway",
        "category": str(category),
        "name": str(name),
        "phase": str(phase or "result"),
        "status": "ok",
        "latencyMs": int(latency_ms) if isinstance(latency_ms, int) and latency_ms >= 0 else None,
        "payload": payload if isinstance(payload, dict) else {},
    }
 

def _build_ui_events_from_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for command in commands:
        kind = str(command.get("kind", "")).strip().lower()
        if kind == "ui.command":
            payload = {
                "commandType": str(command.get("commandType", "")).strip(),
                "actionId": str(command.get("actionId", "")).strip(),
                "text": str(command.get("text", "")).strip(),
                "label": str(command.get("label", "")).strip(),
                "reason": str(command.get("reason", "")).strip(),
            }
            out.append({"name": "ui.command", "payload": payload})
        elif kind == "ui.confirm_request":
            payload = {
                "confirmId": str(command.get("confirmId", "")).strip(),
                "text": str(command.get("text", "")).strip(),
                "timeoutMs": int(command.get("timeoutMs", 0) or 0),
                "actionId": str(command.get("actionId", "")).strip(),
            }
            out.append({"name": "ui.confirm_request", "payload": payload})
    return out


def _find_confirm_request_ts_ms(
    events_path: Path,
    *,
    run_id: str,
    frame_seq: int,
    confirm_id: str,
) -> int | None:
    if not events_path.exists() or not events_path.is_file():
        return None
    latest_ts: int | None = None
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("name", "")).strip().lower() != "ui.confirm_request":
                continue
            if str(row.get("runId", "")).strip() != run_id:
                continue
            row_frame = int(row.get("frameSeq", 0) or 0)
            if row_frame != int(frame_seq):
                continue
            payload = row.get("payload", {})
            payload = payload if isinstance(payload, dict) else {}
            row_confirm_id = str(payload.get("confirmId", "")).strip()
            if row_confirm_id != confirm_id:
                continue
            ts_ms = int(row.get("tsMs", 0) or 0)
            if ts_ms > 0:
                latest_ts = ts_ms
    return latest_ts


def _is_latest_risk_level_critical(
    events_path: Path,
    *,
    run_id: str,
    frame_seq: int,
) -> bool:
    if not events_path.exists() or not events_path.is_file():
        return False
    latest_payload: dict[str, Any] | None = None
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("name", "")).strip().lower() != "plan.generate":
                continue
            if str(row.get("runId", "")).strip() != run_id:
                continue
            row_frame = int(row.get("frameSeq", 0) or 0)
            if row_frame != int(frame_seq):
                continue
            payload = row.get("payload", {})
            if isinstance(payload, dict):
                latest_payload = payload
    if not isinstance(latest_payload, dict):
        return False
    risk_level = str(latest_payload.get("riskLevel", "")).strip().lower()
    return risk_level == "critical"


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
    safety_behavior = quality_payload.get("safetyBehavior", {}) if isinstance(quality_payload, dict) else {}
    confirm_behavior = safety_behavior.get("confirm", {}) if isinstance(safety_behavior, dict) else {}
    confirm_timeouts = int(confirm_behavior.get("timeouts", 0) or 0) if isinstance(confirm_behavior, dict) else 0
    depth_risk = quality_payload.get("depthRisk", {}) if isinstance(quality_payload, dict) else {}
    risk_latency = quality_payload.get("riskLatencyMs", {}) if isinstance(quality_payload, dict) else {}
    ocr_quality = quality_payload.get("ocr", {}) if isinstance(quality_payload, dict) else {}
    seg_quality = quality_payload.get("seg", {}) if isinstance(quality_payload, dict) else {}
    seg_tracking_quality = quality_payload.get("segTracking", {}) if isinstance(quality_payload, dict) else {}
    depth_quality = quality_payload.get("depth", {}) if isinstance(quality_payload, dict) else {}
    slam_quality = quality_payload.get("slam", {}) if isinstance(quality_payload, dict) else {}
    costmap_quality = quality_payload.get("costmap", {}) if isinstance(quality_payload, dict) else {}
    costmap_fused_quality = quality_payload.get("costmapFused", {}) if isinstance(quality_payload, dict) else {}
    slam_error_payload = quality_payload.get("slamError", {}) if isinstance(quality_payload, dict) else {}
    pov_payload = summary.get("pov", {})
    pov_payload = pov_payload if isinstance(pov_payload, dict) else {}
    pov_context = summary.get("povContext", {})
    pov_context = pov_context if isinstance(pov_context, dict) else {}
    pov_context_out = pov_context.get("out", {})
    pov_context_out = pov_context_out if isinstance(pov_context_out, dict) else {}
    plan_payload = summary.get("plan", {})
    plan_payload = plan_payload if isinstance(plan_payload, dict) else {}
    seg_prompt_payload = summary.get("segPrompt", {})
    seg_prompt_payload = seg_prompt_payload if isinstance(seg_prompt_payload, dict) else {}
    seg_context_payload = summary.get("segContext", {})
    seg_context_payload = seg_context_payload if isinstance(seg_context_payload, dict) else {}
    plan_request_payload = summary.get("planRequest", {})
    plan_request_payload = plan_request_payload if isinstance(plan_request_payload, dict) else {}
    plan_context_payload = summary.get("planContext", {})
    plan_context_payload = plan_context_payload if isinstance(plan_context_payload, dict) else {}
    plan_context_pack_payload = summary.get("planContextPack", {})
    plan_context_pack_payload = plan_context_pack_payload if isinstance(plan_context_pack_payload, dict) else {}
    slam_context_payload = summary.get("slamContext", {})
    slam_context_payload = slam_context_payload if isinstance(slam_context_payload, dict) else {}
    frame_e2e_payload = summary.get("frameE2E", {})
    frame_e2e_payload = frame_e2e_payload if isinstance(frame_e2e_payload, dict) else {}
    frame_user_e2e_payload = summary.get("frameUserE2E", {})
    frame_user_e2e_payload = frame_user_e2e_payload if isinstance(frame_user_e2e_payload, dict) else {}
    models_payload = summary.get("models", {})
    models_payload = models_payload if isinstance(models_payload, dict) else {}
    plan_quality_payload = summary.get("planQuality", {})
    plan_quality_payload = plan_quality_payload if isinstance(plan_quality_payload, dict) else {}
    plan_eval_payload = summary.get("planEval", {})
    plan_eval_payload = plan_eval_payload if isinstance(plan_eval_payload, dict) else {}
    critical_misses: int | None = None
    max_delay_frames: int | None = None
    risk_latency_p90: int | None = None
    risk_latency_max: int | None = None
    ocr_cer: float | None = None
    ocr_exact_match_rate: float | None = None
    ocr_coverage: float | None = None
    ocr_latency_p90: int | None = None
    seg_f1_50: float | None = None
    seg_latency_p90: int | None = None
    seg_coverage: float | None = None
    seg_track_coverage: float | None = None
    seg_tracks_total: int | None = None
    seg_id_switches: int | None = None
    depth_absrel: float | None = None
    depth_rmse: float | None = None
    depth_delta1: float | None = None
    depth_coverage: float | None = None
    depth_latency_p90: int | None = None
    costmap_coverage: float | None = None
    costmap_latency_p90: int | None = None
    costmap_density_mean: float | None = None
    costmap_dynamic_filter_rate_mean: float | None = None
    costmap_fused_coverage: float | None = None
    costmap_fused_latency_p90: int | None = None
    costmap_fused_iou_p90: float | None = None
    costmap_fused_flicker_rate_mean: float | None = None
    costmap_fused_shift_used_rate: float | None = None
    costmap_fused_shift_gate_reject_rate: float | None = None
    costmap_fused_shift_gate_top_reason: str | None = None
    slam_tracking_rate: float | None = None
    slam_lost_rate: float | None = None
    slam_relocalized: int | None = None
    slam_latency_p90: int | None = None
    slam_align_residual_p90: int | None = None
    slam_align_mode: str | None = None
    slam_ate_rmse: float | None = None
    slam_rpe_trans_rmse: float | None = None
    seg_mask_f1_50: float | None = None
    seg_mask_coverage: float | None = None
    seg_mask_mean_iou: float | None = None
    seg_ctx_chars: int | None = None
    seg_ctx_segments: int | None = None
    seg_ctx_trunc_dropped: int | None = None
    seg_prompt_present = bool(seg_prompt_payload.get("present")) if isinstance(seg_prompt_payload, dict) else False
    seg_prompt_text_chars_total: int | None = None
    seg_prompt_chars_out: int | None = None
    seg_prompt_targets_out: int | None = None
    seg_prompt_trunc_dropped: int | None = None
    seg_prompt_trunc_rate: float | None = None
    pov_present = bool(pov_payload.get("present")) if isinstance(pov_payload, dict) else False
    pov_counts = pov_payload.get("counts", {}) if isinstance(pov_payload.get("counts"), dict) else {}
    pov_time = pov_payload.get("time", {}) if isinstance(pov_payload.get("time"), dict) else {}
    pov_budget = pov_payload.get("budget", {}) if isinstance(pov_payload.get("budget"), dict) else {}
    pov_decisions = int(_read_float(pov_counts, "decisions") or 0)
    pov_duration_ms = _read_float(pov_time, "durationMs")
    pov_decision_per_min = _read_float(pov_time, "decisionPerMin")
    pov_token_approx = int(_read_float(pov_budget, "tokenApprox") or 0)
    pov_context_token_approx_raw = _read_float(pov_context_out, "tokenApprox")
    pov_context_chars_raw = _read_float(pov_context_out, "charsTotal")
    pov_context_token_approx = int(pov_context_token_approx_raw) if pov_context_token_approx_raw is not None else None
    pov_context_chars = int(pov_context_chars_raw) if pov_context_chars_raw is not None else None
    has_pov_context = bool(pov_context_token_approx is not None)
    plan_present = bool(plan_payload.get("present"))
    plan_risk_level = str(plan_payload.get("riskLevel", "")).strip() or None
    plan_actions = 0
    plan_guardrails = 0
    plan_has_stop = False
    plan_has_confirm = False
    plan_score: float | None = None
    plan_fallback_used = False
    plan_json_valid: bool | None = None
    plan_prompt_version: str | None = None
    plan_latency_p90: int | None = None
    confirm_requests = int((_read_float(summary, "confirm_request") or 0.0))
    plan_confirm_timeouts = confirm_timeouts
    plan_overcautious_rate: float | None = None
    plan_guardrail_override_rate: float | None = None
    plan_rule_applied = False
    plan_rule_hint: str | None = None
    plan_req_seg_chars_p90: int | None = None
    plan_req_seg_trunc_dropped: int | None = None
    plan_req_pov_chars_p90: int | None = None
    plan_req_fallback_used = False
    plan_ctx_used = False
    plan_ctx_used_rate: float | None = None
    plan_seg_ctx_coverage: float | None = None
    plan_pov_ctx_coverage: float | None = None
    plan_slam_ctx_coverage: float | None = None
    plan_slam_ctx_hit_rate: float | None = None
    plan_slam_ctx_used_rate: float | None = None
    plan_costmap_ctx_coverage_p90: float | None = None
    plan_costmap_ctx_used_rate: float | None = None
    plan_ctx_chars_p90: int | None = None
    plan_ctx_trunc_rate: float | None = None
    plan_ctx_seg_chars_p90: int | None = None
    plan_ctx_pov_chars_p90: int | None = None
    plan_ctx_risk_chars_p90: int | None = None
    slam_ctx_present = False
    slam_ctx_chars_p90: int | None = None
    slam_ctx_trunc_rate: float | None = None
    slam_tracking_rate_mean: float | None = None
    frame_e2e_p90: int | None = None
    frame_e2e_max: int | None = None
    frame_seg_p90: int | None = None
    frame_risk_p90: int | None = None
    frame_plan_p90: int | None = None
    frame_execute_p90: int | None = None
    frame_user_e2e_p90: int | None = None
    frame_user_e2e_max: int | None = None
    ack_coverage: float | None = None
    frame_user_e2e_tts_p90: int | None = None
    frame_user_e2e_tts_max: int | None = None
    frame_user_e2e_ar_p90: int | None = None
    frame_user_e2e_ar_max: int | None = None
    ack_kind_diversity: int = 0
    models_missing_required: int | None = None
    models_enabled_total: int | None = None
    plan_actions_payload = plan_payload.get("actions")
    if isinstance(plan_actions_payload, dict):
        raw_actions = _read_float(plan_actions_payload, "count")
        if raw_actions is not None:
            plan_actions = int(raw_actions)
        types = plan_actions_payload.get("types")
        if isinstance(types, list):
            normalized_types = {str(item).strip().lower() for item in types if str(item).strip()}
            plan_has_stop = "stop" in normalized_types
            plan_has_confirm = "confirm" in normalized_types
    plan_guardrails_payload = plan_payload.get("guardrailsApplied")
    if isinstance(plan_guardrails_payload, list):
        plan_guardrails = len([item for item in plan_guardrails_payload if str(item).strip()])
    if isinstance(plan_quality_payload, dict):
        risk_level_override = str(plan_quality_payload.get("riskLevel", "")).strip()
        if risk_level_override:
            plan_risk_level = risk_level_override
        has_stop_override = plan_quality_payload.get("hasStop")
        if isinstance(has_stop_override, bool):
            plan_has_stop = has_stop_override
        has_confirm_override = plan_quality_payload.get("hasConfirm")
        if isinstance(has_confirm_override, bool):
            plan_has_confirm = has_confirm_override
        score_raw = _read_float(plan_quality_payload, "score")
        if score_raw is not None:
            plan_score = float(score_raw)
        fallback_used_raw = plan_quality_payload.get("fallbackUsed")
        if isinstance(fallback_used_raw, bool):
            plan_fallback_used = fallback_used_raw
        json_valid_raw = plan_quality_payload.get("jsonValid")
        if isinstance(json_valid_raw, bool):
            plan_json_valid = json_valid_raw
        prompt_version_raw = str(plan_quality_payload.get("promptVersion", "")).strip()
        if prompt_version_raw:
            plan_prompt_version = prompt_version_raw
    if isinstance(plan_eval_payload, dict) and bool(plan_eval_payload.get("present")):
        latency_payload = plan_eval_payload.get("latencyMs")
        latency_payload = latency_payload if isinstance(latency_payload, dict) else {}
        p90_raw = _read_float(latency_payload, "p90")
        if p90_raw is not None:
            plan_latency_p90 = int(p90_raw)
        confirm_payload = plan_eval_payload.get("confirm")
        confirm_payload = confirm_payload if isinstance(confirm_payload, dict) else {}
        requests_raw = _read_float(confirm_payload, "requests")
        if requests_raw is not None:
            confirm_requests = int(requests_raw)
        timeouts_raw = _read_float(confirm_payload, "timeouts")
        if timeouts_raw is not None:
            plan_confirm_timeouts = int(timeouts_raw)
        guardrail_payload = plan_eval_payload.get("guardrails")
        guardrail_payload = guardrail_payload if isinstance(guardrail_payload, dict) else {}
        override_raw = _read_float(guardrail_payload, "overrideRate")
        if override_raw is not None:
            plan_guardrail_override_rate = float(override_raw)
        overcautious_payload = plan_eval_payload.get("overcautious")
        overcautious_payload = overcautious_payload if isinstance(overcautious_payload, dict) else {}
        overcautious_raw = _read_float(overcautious_payload, "rate")
        if overcautious_raw is not None:
            plan_overcautious_rate = float(overcautious_raw)
        plan_rule_applied = int(plan_eval_payload.get("ruleAppliedCount", 0) or 0) > 0
        hint_text = str(plan_eval_payload.get("ruleHazardHintTop", "")).strip()
        if hint_text:
            plan_rule_hint = hint_text
    planner_payload = plan_payload.get("planner")
    planner_payload = planner_payload if isinstance(planner_payload, dict) else {}
    if not plan_prompt_version:
        prompt_version_raw = str(planner_payload.get("promptVersion", "")).strip()
        if prompt_version_raw:
            plan_prompt_version = prompt_version_raw
    if plan_json_valid is None:
        json_valid_raw = planner_payload.get("jsonValid")
        if isinstance(json_valid_raw, bool):
            plan_json_valid = json_valid_raw
    if not plan_fallback_used and isinstance(planner_payload.get("fallbackUsed"), bool):
        plan_fallback_used = bool(planner_payload.get("fallbackUsed"))
    if isinstance(plan_request_payload, dict) and bool(plan_request_payload.get("present")):
        seg_chars_raw = _read_float(plan_request_payload, "segCharsP90")
        if seg_chars_raw is not None:
            plan_req_seg_chars_p90 = int(seg_chars_raw)
        seg_trunc_raw = _read_float(plan_request_payload, "segTruncSegmentsDroppedTotal")
        if seg_trunc_raw is not None:
            plan_req_seg_trunc_dropped = int(seg_trunc_raw)
        pov_chars_raw = _read_float(plan_request_payload, "povCharsP90")
        if pov_chars_raw is not None:
            plan_req_pov_chars_p90 = int(pov_chars_raw)
        fallback_count_raw = _read_float(plan_request_payload, "fallbackUsedCount")
        if fallback_count_raw is not None:
            plan_req_fallback_used = int(fallback_count_raw) > 0
    if isinstance(plan_context_payload, dict) and bool(plan_context_payload.get("present")):
        ctx_used_rate_raw = _read_float(plan_context_payload, "contextUsedRate")
        if ctx_used_rate_raw is not None:
            plan_ctx_used_rate = float(ctx_used_rate_raw)
            plan_ctx_used = float(ctx_used_rate_raw) > 0.0
        seg_ctx_payload = plan_context_payload.get("seg")
        seg_ctx_payload = seg_ctx_payload if isinstance(seg_ctx_payload, dict) else {}
        seg_cov_raw = _read_float(seg_ctx_payload, "coverageMean")
        if seg_cov_raw is not None:
            plan_seg_ctx_coverage = float(seg_cov_raw)
        pov_ctx_payload = plan_context_payload.get("pov")
        pov_ctx_payload = pov_ctx_payload if isinstance(pov_ctx_payload, dict) else {}
        pov_cov_raw = _read_float(pov_ctx_payload, "coverageMean")
        if pov_cov_raw is not None:
            plan_pov_ctx_coverage = float(pov_cov_raw)
        slam_ctx_payload = plan_context_payload.get("slam")
        slam_ctx_payload = slam_ctx_payload if isinstance(slam_ctx_payload, dict) else {}
        slam_cov_raw = _read_float(slam_ctx_payload, "coverageMean")
        if slam_cov_raw is not None:
            plan_slam_ctx_coverage = float(slam_cov_raw)
        slam_hit_raw = _read_float(slam_ctx_payload, "hitRate")
        if slam_hit_raw is not None:
            plan_slam_ctx_hit_rate = float(slam_hit_raw)
        slam_used_raw = _read_float(slam_ctx_payload, "contextUsedRate")
        if slam_used_raw is not None:
            plan_slam_ctx_used_rate = float(slam_used_raw)
        costmap_ctx_payload = plan_context_payload.get("costmap")
        costmap_ctx_payload = costmap_ctx_payload if isinstance(costmap_ctx_payload, dict) else {}
        costmap_cov_raw = _read_float(costmap_ctx_payload, "coverageP90")
        if costmap_cov_raw is None:
            costmap_cov_raw = _read_float(costmap_ctx_payload, "coverageMean")
        if costmap_cov_raw is not None:
            plan_costmap_ctx_coverage_p90 = float(costmap_cov_raw)
        costmap_used_raw = _read_float(costmap_ctx_payload, "contextUsedRate")
        if costmap_used_raw is not None:
            plan_costmap_ctx_used_rate = float(costmap_used_raw)
    if isinstance(plan_context_pack_payload, dict) and bool(plan_context_pack_payload.get("present")):
        out_payload = plan_context_pack_payload.get("out")
        out_payload = out_payload if isinstance(out_payload, dict) else {}
        trunc_payload = plan_context_pack_payload.get("truncation")
        trunc_payload = trunc_payload if isinstance(trunc_payload, dict) else {}
        chars_raw = _read_float(out_payload, "charsTotalP90")
        if chars_raw is not None:
            plan_ctx_chars_p90 = int(chars_raw)
        seg_chars_raw = _read_float(out_payload, "segCharsP90")
        if seg_chars_raw is not None:
            plan_ctx_seg_chars_p90 = int(seg_chars_raw)
        pov_chars_raw = _read_float(out_payload, "povCharsP90")
        if pov_chars_raw is not None:
            plan_ctx_pov_chars_p90 = int(pov_chars_raw)
        risk_chars_raw = _read_float(out_payload, "riskCharsP90")
        if risk_chars_raw is not None:
            plan_ctx_risk_chars_p90 = int(risk_chars_raw)
        trunc_rate_raw = _read_float(trunc_payload, "truncationRate")
        if trunc_rate_raw is not None:
            plan_ctx_trunc_rate = float(trunc_rate_raw)
    if isinstance(slam_context_payload, dict) and bool(slam_context_payload.get("present")):
        slam_ctx_present = True
        out_payload = slam_context_payload.get("out")
        out_payload = out_payload if isinstance(out_payload, dict) else {}
        trunc_payload = slam_context_payload.get("truncation")
        trunc_payload = trunc_payload if isinstance(trunc_payload, dict) else {}
        health_payload = slam_context_payload.get("health")
        health_payload = health_payload if isinstance(health_payload, dict) else {}
        slam_ctx_chars_raw = _read_float(out_payload, "charsTotalP90")
        if slam_ctx_chars_raw is not None:
            slam_ctx_chars_p90 = int(slam_ctx_chars_raw)
        slam_ctx_trunc_raw = _read_float(trunc_payload, "truncationRate")
        if slam_ctx_trunc_raw is not None:
            slam_ctx_trunc_rate = float(slam_ctx_trunc_raw)
        slam_tracking_rate_raw = _read_float(health_payload, "trackingRateMean")
        if slam_tracking_rate_raw is not None:
            slam_tracking_rate_mean = float(slam_tracking_rate_raw)
    if isinstance(frame_e2e_payload, dict) and bool(frame_e2e_payload.get("present")):
        frame_total = frame_e2e_payload.get("totalMs")
        frame_total = frame_total if isinstance(frame_total, dict) else {}
        frame_parts = frame_e2e_payload.get("partsMs")
        frame_parts = frame_parts if isinstance(frame_parts, dict) else {}
        frame_e2e_p90_raw = _read_float(frame_total, "p90")
        if frame_e2e_p90_raw is not None:
            frame_e2e_p90 = int(frame_e2e_p90_raw)
        frame_e2e_max_raw = _read_float(frame_total, "max")
        if frame_e2e_max_raw is not None:
            frame_e2e_max = int(frame_e2e_max_raw)
        seg_part = frame_parts.get("segMs")
        seg_part = seg_part if isinstance(seg_part, dict) else {}
        frame_seg_p90_raw = _read_float(seg_part, "p90")
        if frame_seg_p90_raw is not None:
            frame_seg_p90 = int(frame_seg_p90_raw)
        risk_part = frame_parts.get("riskMs")
        risk_part = risk_part if isinstance(risk_part, dict) else {}
        frame_risk_p90_raw = _read_float(risk_part, "p90")
        if frame_risk_p90_raw is not None:
            frame_risk_p90 = int(frame_risk_p90_raw)
        plan_part = frame_parts.get("planMs")
        plan_part = plan_part if isinstance(plan_part, dict) else {}
        frame_plan_p90_raw = _read_float(plan_part, "p90")
        if frame_plan_p90_raw is not None:
            frame_plan_p90 = int(frame_plan_p90_raw)
        execute_part = frame_parts.get("executeMs")
        execute_part = execute_part if isinstance(execute_part, dict) else {}
        frame_execute_p90_raw = _read_float(execute_part, "p90")
        if frame_execute_p90_raw is not None:
            frame_execute_p90 = int(frame_execute_p90_raw)
    if isinstance(frame_user_e2e_payload, dict) and bool(frame_user_e2e_payload.get("present")):
        user_total = frame_user_e2e_payload.get("totalMs")
        user_total = user_total if isinstance(user_total, dict) else {}
        user_cov = frame_user_e2e_payload.get("coverage")
        user_cov = user_cov if isinstance(user_cov, dict) else {}
        user_p90_raw = _read_float(user_total, "p90")
        if user_p90_raw is not None:
            frame_user_e2e_p90 = int(user_p90_raw)
        user_max_raw = _read_float(user_total, "max")
        if user_max_raw is not None:
            frame_user_e2e_max = int(user_max_raw)
        ack_cov_raw = _read_float(user_cov, "ratio")
        if ack_cov_raw is not None:
            ack_coverage = float(ack_cov_raw)
        by_kind_payload = frame_user_e2e_payload.get("byKind")
        by_kind_payload = by_kind_payload if isinstance(by_kind_payload, dict) else {}
        ack_kind_diversity = len([key for key in by_kind_payload.keys() if str(key).strip()])
        tts_payload = by_kind_payload.get("tts")
        tts_payload = tts_payload if isinstance(tts_payload, dict) else {}
        tts_total = tts_payload.get("totalMs")
        tts_total = tts_total if isinstance(tts_total, dict) else {}
        tts_p90_raw = _read_float(tts_total, "p90")
        if tts_p90_raw is not None:
            frame_user_e2e_tts_p90 = int(tts_p90_raw)
        tts_max_raw = _read_float(tts_total, "max")
        if tts_max_raw is not None:
            frame_user_e2e_tts_max = int(tts_max_raw)
        ar_payload = by_kind_payload.get("ar")
        ar_payload = ar_payload if isinstance(ar_payload, dict) else {}
        ar_total = ar_payload.get("totalMs")
        ar_total = ar_total if isinstance(ar_total, dict) else {}
        ar_p90_raw = _read_float(ar_total, "p90")
        if ar_p90_raw is not None:
            frame_user_e2e_ar_p90 = int(ar_p90_raw)
        ar_max_raw = _read_float(ar_total, "max")
        if ar_max_raw is not None:
            frame_user_e2e_ar_max = int(ar_max_raw)
    if isinstance(models_payload, dict) and bool(models_payload.get("present")):
        missing_raw = _read_float(models_payload, "missingRequiredTotal")
        if missing_raw is not None:
            models_missing_required = int(missing_raw)
        enabled_raw = _read_float(models_payload, "enabledTotal")
        if enabled_raw is not None:
            models_enabled_total = int(enabled_raw)
    if isinstance(depth_risk, dict):
        critical = depth_risk.get("critical", {})
        delay = depth_risk.get("detectionDelayFrames", {})
        if isinstance(critical, dict):
            raw = _read_float(critical, "missCriticalCount")
            if raw is not None:
                critical_misses = int(raw)
        if isinstance(delay, dict):
            raw = _read_float(delay, "max")
            if raw is not None:
                max_delay_frames = int(raw)
    if isinstance(risk_latency, dict):
        raw_p90 = _read_float(risk_latency, "p90")
        if raw_p90 is not None:
            risk_latency_p90 = int(raw_p90)
        raw_max = _read_float(risk_latency, "max")
        if raw_max is not None:
            risk_latency_max = int(raw_max)
    if isinstance(ocr_quality, dict):
        raw_cer = _read_float(ocr_quality, "cer")
        if raw_cer is not None:
            ocr_cer = float(raw_cer)
        raw_exact = _read_float(ocr_quality, "exactMatchRate")
        if raw_exact is not None:
            ocr_exact_match_rate = float(raw_exact)
        raw_ocr_cov = _read_float(ocr_quality, "coverage")
        if raw_ocr_cov is not None:
            ocr_coverage = float(raw_ocr_cov)
        ocr_latency = ocr_quality.get("latencyMs")
        ocr_latency = ocr_latency if isinstance(ocr_latency, dict) else {}
        raw_ocr_p90 = _read_float(ocr_latency, "p90")
        if raw_ocr_p90 is not None:
            ocr_latency_p90 = int(raw_ocr_p90)
    if isinstance(seg_quality, dict):
        raw_f1 = _read_float(seg_quality, "f1At50")
        if raw_f1 is not None:
            seg_f1_50 = float(raw_f1)
        seg_latency = seg_quality.get("latencyMs")
        seg_latency = seg_latency if isinstance(seg_latency, dict) else {}
        raw_seg_p90 = _read_float(seg_latency, "p90")
        if raw_seg_p90 is not None:
            seg_latency_p90 = int(raw_seg_p90)
        raw_cov = _read_float(seg_quality, "coverage")
        if raw_cov is not None:
            seg_coverage = float(raw_cov)
        raw_mask_f1 = _read_float(seg_quality, "maskF1_50")
        if raw_mask_f1 is not None:
            seg_mask_f1_50 = float(raw_mask_f1)
        raw_mask_cov = _read_float(seg_quality, "maskCoverage")
        if raw_mask_cov is not None:
            seg_mask_coverage = float(raw_mask_cov)
        raw_mask_iou = _read_float(seg_quality, "maskMeanIoU")
        if raw_mask_iou is not None:
            seg_mask_mean_iou = float(raw_mask_iou)
    if isinstance(seg_tracking_quality, dict):
        raw_track_cov = _read_float(seg_tracking_quality, "trackCoverage")
        if raw_track_cov is not None:
            seg_track_coverage = float(raw_track_cov)
        raw_tracks_total = _read_float(seg_tracking_quality, "tracksTotal")
        if raw_tracks_total is not None:
            seg_tracks_total = int(raw_tracks_total)
        raw_switches = _read_float(seg_tracking_quality, "idSwitchCount")
        if raw_switches is not None:
            seg_id_switches = int(raw_switches)
    if isinstance(depth_quality, dict):
        raw_absrel = _read_float(depth_quality, "absRel")
        if raw_absrel is not None:
            depth_absrel = float(raw_absrel)
        raw_rmse = _read_float(depth_quality, "rmse")
        if raw_rmse is not None:
            depth_rmse = float(raw_rmse)
        raw_delta1 = _read_float(depth_quality, "delta1")
        if raw_delta1 is not None:
            depth_delta1 = float(raw_delta1)
        raw_depth_cov = _read_float(depth_quality, "coverage")
        if raw_depth_cov is not None:
            depth_coverage = float(raw_depth_cov)
        depth_latency = depth_quality.get("latencyMs")
        depth_latency = depth_latency if isinstance(depth_latency, dict) else {}
        raw_depth_p90 = _read_float(depth_latency, "p90")
        if raw_depth_p90 is not None:
            depth_latency_p90 = int(raw_depth_p90)
    if isinstance(costmap_quality, dict):
        raw_costmap_cov = _read_float(costmap_quality, "coverage")
        if raw_costmap_cov is not None:
            costmap_coverage = float(raw_costmap_cov)
        costmap_latency = costmap_quality.get("latencyMs")
        costmap_latency = costmap_latency if isinstance(costmap_latency, dict) else {}
        raw_costmap_latency_p90 = _read_float(costmap_latency, "p90")
        if raw_costmap_latency_p90 is not None:
            costmap_latency_p90 = int(raw_costmap_latency_p90)
        costmap_density = costmap_quality.get("densityMean")
        costmap_density = costmap_density if isinstance(costmap_density, dict) else {}
        raw_density_mean = _read_float(costmap_density, "mean")
        if raw_density_mean is not None:
            costmap_density_mean = float(raw_density_mean)
        dynamic_filter = costmap_quality.get("dynamicFilteredRate")
        dynamic_filter = dynamic_filter if isinstance(dynamic_filter, dict) else {}
        raw_dynamic_mean = _read_float(dynamic_filter, "mean")
        if raw_dynamic_mean is not None:
            costmap_dynamic_filter_rate_mean = float(raw_dynamic_mean)
    if isinstance(costmap_fused_quality, dict):
        raw_costmap_fused_cov = _read_float(costmap_fused_quality, "coverage")
        if raw_costmap_fused_cov is not None:
            costmap_fused_coverage = float(raw_costmap_fused_cov)
        costmap_fused_latency = costmap_fused_quality.get("latencyMs")
        costmap_fused_latency = costmap_fused_latency if isinstance(costmap_fused_latency, dict) else {}
        raw_costmap_fused_latency_p90 = _read_float(costmap_fused_latency, "p90")
        if raw_costmap_fused_latency_p90 is not None:
            costmap_fused_latency_p90 = int(raw_costmap_fused_latency_p90)
        fused_stability = costmap_fused_quality.get("stability")
        fused_stability = fused_stability if isinstance(fused_stability, dict) else {}
        raw_iou_p90 = _read_float(fused_stability, "iouPrevP90")
        if raw_iou_p90 is None:
            raw_iou_p90 = _read_float(fused_stability, "iouPrevMean")
        if raw_iou_p90 is not None:
            costmap_fused_iou_p90 = float(raw_iou_p90)
        raw_flicker_mean = _read_float(fused_stability, "flickerRatePrevMean")
        if raw_flicker_mean is not None:
            costmap_fused_flicker_rate_mean = float(raw_flicker_mean)
        raw_shift_used_rate = _read_float(costmap_fused_quality, "shiftUsedRate")
        if raw_shift_used_rate is not None:
            costmap_fused_shift_used_rate = float(raw_shift_used_rate)
        raw_shift_reject_rate = _read_float(costmap_fused_quality, "shiftGateRejectRate")
        if raw_shift_reject_rate is not None:
            costmap_fused_shift_gate_reject_rate = float(raw_shift_reject_rate)
        top_reasons = costmap_fused_quality.get("shiftGateTopReasons")
        top_reasons = top_reasons if isinstance(top_reasons, list) else []
        if top_reasons:
            first_reason = top_reasons[0]
            if isinstance(first_reason, dict):
                reason_text = str(first_reason.get("reason", "")).strip()
                if reason_text:
                    costmap_fused_shift_gate_top_reason = reason_text
    if isinstance(slam_quality, dict):
        tracking_payload = slam_quality.get("tracking")
        tracking_payload = tracking_payload if isinstance(tracking_payload, dict) else {}
        raw_tracking_rate = _read_float(tracking_payload, "trackingRate")
        if raw_tracking_rate is not None:
            slam_tracking_rate = float(raw_tracking_rate)
        raw_lost_rate = _read_float(tracking_payload, "lostRate")
        if raw_lost_rate is not None:
            slam_lost_rate = float(raw_lost_rate)
        raw_relocalized = _read_float(tracking_payload, "relocalizedCount")
        if raw_relocalized is not None:
            slam_relocalized = int(raw_relocalized)
        slam_latency = slam_quality.get("latencyMs")
        slam_latency = slam_latency if isinstance(slam_latency, dict) else {}
        raw_slam_p90 = _read_float(slam_latency, "p90")
        if raw_slam_p90 is not None:
            slam_latency_p90 = int(raw_slam_p90)
        alignment_payload = slam_quality.get("alignment")
        alignment_payload = alignment_payload if isinstance(alignment_payload, dict) else {}
        residual_payload = alignment_payload.get("residualMs")
        residual_payload = residual_payload if isinstance(residual_payload, dict) else {}
        raw_slam_align_p90 = _read_float(residual_payload, "p90")
        if raw_slam_align_p90 is not None:
            slam_align_residual_p90 = int(raw_slam_align_p90)
        slam_align_mode_text = str(alignment_payload.get("mode", "")).strip()
        if slam_align_mode_text:
            slam_align_mode = slam_align_mode_text
    if isinstance(slam_error_payload, dict):
        raw_slam_ate_rmse = _read_float(slam_error_payload, "ate_rmse_m")
        if raw_slam_ate_rmse is not None:
            slam_ate_rmse = float(raw_slam_ate_rmse)
        raw_slam_rpe_trans = _read_float(slam_error_payload, "rpe_trans_rmse_m")
        if raw_slam_rpe_trans is not None:
            slam_rpe_trans_rmse = float(raw_slam_rpe_trans)
    seg_context_stats = seg_context_payload.get("stats")
    seg_context_stats = seg_context_stats if isinstance(seg_context_stats, dict) else {}
    seg_context_out = seg_context_stats.get("out")
    seg_context_out = seg_context_out if isinstance(seg_context_out, dict) else {}
    seg_context_truncation = seg_context_stats.get("truncation")
    seg_context_truncation = seg_context_truncation if isinstance(seg_context_truncation, dict) else {}
    seg_ctx_chars_raw = _read_float(seg_context_out, "charsTotal")
    if seg_ctx_chars_raw is not None:
        seg_ctx_chars = int(seg_ctx_chars_raw)
    seg_ctx_segments_raw = _read_float(seg_context_out, "segments")
    if seg_ctx_segments_raw is not None:
        seg_ctx_segments = int(seg_ctx_segments_raw)
    seg_ctx_trunc_raw = _read_float(seg_context_truncation, "segmentsDropped")
    if seg_ctx_trunc_raw is not None:
        seg_ctx_trunc_dropped = int(seg_ctx_trunc_raw)
    seg_prompt_text_raw = _read_float(seg_prompt_payload, "textCharsTotal")
    if seg_prompt_text_raw is not None:
        seg_prompt_text_chars_total = int(seg_prompt_text_raw)
    seg_prompt_out = seg_prompt_payload.get("out")
    seg_prompt_out = seg_prompt_out if isinstance(seg_prompt_out, dict) else {}
    seg_prompt_truncation = seg_prompt_payload.get("truncation")
    seg_prompt_truncation = seg_prompt_truncation if isinstance(seg_prompt_truncation, dict) else {}
    seg_prompt_chars_out_raw = _read_float(seg_prompt_out, "charsTotal")
    if seg_prompt_chars_out_raw is not None:
        seg_prompt_chars_out = int(seg_prompt_chars_out_raw)
    seg_prompt_targets_out_raw = _read_float(seg_prompt_out, "targetsCountTotal")
    if seg_prompt_targets_out_raw is not None:
        seg_prompt_targets_out = int(seg_prompt_targets_out_raw)
    seg_prompt_targets_dropped = _read_float(seg_prompt_truncation, "targetsDropped")
    seg_prompt_boxes_dropped = _read_float(seg_prompt_truncation, "boxesDropped")
    seg_prompt_points_dropped = _read_float(seg_prompt_truncation, "pointsDropped")
    seg_prompt_text_dropped = _read_float(seg_prompt_truncation, "textCharsDropped")
    dropped_total = 0.0
    for value in (seg_prompt_targets_dropped, seg_prompt_boxes_dropped, seg_prompt_points_dropped, seg_prompt_text_dropped):
        if value is not None:
            dropped_total += float(value)
    if seg_prompt_present:
        seg_prompt_trunc_dropped = int(max(0.0, dropped_total))
    seg_prompt_trunc_rate_raw = _read_float(seg_prompt_payload, "truncationRate")
    if seg_prompt_trunc_rate_raw is not None:
        seg_prompt_trunc_rate = float(seg_prompt_trunc_rate_raw)
    elif seg_prompt_present:
        seg_prompt_trunc_rate = 0.0

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
        "confirm_timeouts": plan_confirm_timeouts,
        "confirm_requests": confirm_requests,
        "plan_confirm_timeouts": plan_confirm_timeouts,
        "missCriticalCount": critical_misses,
        "critical_misses": critical_misses,
        "max_delay_frames": max_delay_frames,
        "riskLatencyP90": risk_latency_p90,
        "riskLatencyMax": risk_latency_max,
        "risk_latency_p90": risk_latency_p90,
        "risk_latency_max": risk_latency_max,
        "ocr_cer": ocr_cer,
        "ocr_exact_match_rate": ocr_exact_match_rate,
        "ocr_coverage": ocr_coverage,
        "ocr_latency_p90": ocr_latency_p90,
        "seg_f1_50": seg_f1_50,
        "seg_latency_p90": seg_latency_p90,
        "seg_coverage": seg_coverage,
        "seg_track_coverage": seg_track_coverage,
        "seg_tracks_total": seg_tracks_total,
        "seg_id_switches": seg_id_switches,
        "depth_absrel": depth_absrel,
        "depth_rmse": depth_rmse,
        "depth_delta1": depth_delta1,
        "depth_coverage": depth_coverage,
        "depth_latency_p90": depth_latency_p90,
        "costmap_coverage": costmap_coverage,
        "costmap_latency_p90": costmap_latency_p90,
        "costmap_density_mean": costmap_density_mean,
        "costmap_dynamic_filter_rate_mean": costmap_dynamic_filter_rate_mean,
        "costmap_fused_coverage": costmap_fused_coverage,
        "costmap_fused_latency_p90": costmap_fused_latency_p90,
        "costmap_fused_iou_p90": costmap_fused_iou_p90,
        "costmap_fused_flicker_rate_mean": costmap_fused_flicker_rate_mean,
        "costmap_fused_shift_used_rate": costmap_fused_shift_used_rate,
        "costmap_fused_shift_gate_reject_rate": costmap_fused_shift_gate_reject_rate,
        "costmap_fused_shift_gate_top_reason": costmap_fused_shift_gate_top_reason,
        "slam_tracking_rate": slam_tracking_rate,
        "slam_lost_rate": slam_lost_rate,
        "slam_relocalized": slam_relocalized,
        "slam_latency_p90": slam_latency_p90,
        "slam_align_residual_p90": slam_align_residual_p90,
        "slam_align_mode": slam_align_mode,
        "slam_ate_rmse": slam_ate_rmse,
        "slam_rpe_trans_rmse": slam_rpe_trans_rmse,
        "seg_mask_f1_50": seg_mask_f1_50,
        "seg_mask_coverage": seg_mask_coverage,
        "seg_mask_mean_iou": seg_mask_mean_iou,
        "seg_ctx_chars": seg_ctx_chars,
        "seg_ctx_segments": seg_ctx_segments,
        "seg_ctx_trunc_dropped": seg_ctx_trunc_dropped,
        "seg_prompt_present": seg_prompt_present,
        "seg_prompt_text_chars_total": seg_prompt_text_chars_total,
        "seg_prompt_chars_out": seg_prompt_chars_out,
        "seg_prompt_targets_out": seg_prompt_targets_out,
        "seg_prompt_trunc_dropped": seg_prompt_trunc_dropped,
        "seg_prompt_trunc_rate": seg_prompt_trunc_rate,
        "pov_present": pov_present,
        "pov_decisions": pov_decisions,
        "pov_duration_ms": int(pov_duration_ms) if pov_duration_ms is not None else None,
        "pov_token_approx": pov_token_approx,
        "pov_decision_per_min": pov_decision_per_min,
        "has_pov_context": has_pov_context,
        "pov_context_token_approx": pov_context_token_approx,
        "pov_context_chars": pov_context_chars,
        "plan_present": plan_present,
        "plan_risk_level": plan_risk_level,
        "plan_actions": plan_actions,
        "plan_guardrails": plan_guardrails,
        "plan_has_stop": plan_has_stop,
        "plan_has_confirm": plan_has_confirm,
        "plan_score": plan_score,
        "plan_fallback_used": plan_fallback_used,
        "plan_json_valid": plan_json_valid,
        "plan_prompt_version": plan_prompt_version,
        "plan_latency_p90": plan_latency_p90,
        "plan_overcautious_rate": plan_overcautious_rate,
        "plan_guardrail_override_rate": plan_guardrail_override_rate,
        "plan_rule_applied": plan_rule_applied,
        "plan_rule_hint": plan_rule_hint,
        "plan_req_seg_chars_p90": plan_req_seg_chars_p90,
        "plan_req_seg_trunc_dropped": plan_req_seg_trunc_dropped,
        "plan_req_pov_chars_p90": plan_req_pov_chars_p90,
        "plan_req_fallback_used": plan_req_fallback_used,
        "plan_ctx_used": plan_ctx_used,
        "plan_ctx_used_rate": plan_ctx_used_rate,
        "plan_seg_ctx_coverage": plan_seg_ctx_coverage,
        "plan_pov_ctx_coverage": plan_pov_ctx_coverage,
        "plan_slam_ctx_coverage": plan_slam_ctx_coverage,
        "plan_slam_ctx_hit_rate": plan_slam_ctx_hit_rate,
        "plan_slam_ctx_used_rate": plan_slam_ctx_used_rate,
        "plan_costmap_ctx_coverage_p90": plan_costmap_ctx_coverage_p90,
        "plan_costmap_ctx_used_rate": plan_costmap_ctx_used_rate,
        "plan_ctx_chars_p90": plan_ctx_chars_p90,
        "plan_ctx_trunc_rate": plan_ctx_trunc_rate,
        "plan_ctx_seg_chars_p90": plan_ctx_seg_chars_p90,
        "plan_ctx_pov_chars_p90": plan_ctx_pov_chars_p90,
        "plan_ctx_risk_chars_p90": plan_ctx_risk_chars_p90,
        "slam_ctx_present": slam_ctx_present,
        "slam_ctx_chars_p90": slam_ctx_chars_p90,
        "slam_ctx_trunc_rate": slam_ctx_trunc_rate,
        "slam_tracking_rate_mean": slam_tracking_rate_mean,
        "frame_e2e_p90": frame_e2e_p90,
        "frame_e2e_max": frame_e2e_max,
        "frame_seg_p90": frame_seg_p90,
        "frame_risk_p90": frame_risk_p90,
        "frame_plan_p90": frame_plan_p90,
        "frame_execute_p90": frame_execute_p90,
        "frame_user_e2e_p90": frame_user_e2e_p90,
        "frame_user_e2e_max": frame_user_e2e_max,
        "frame_user_e2e_tts_p90": frame_user_e2e_tts_p90,
        "frame_user_e2e_tts_max": frame_user_e2e_tts_max,
        "frame_user_e2e_ar_p90": frame_user_e2e_ar_p90,
        "frame_user_e2e_ar_max": frame_user_e2e_ar_max,
        "ack_kind_diversity": int(ack_kind_diversity),
        "ack_coverage": ack_coverage,
        "models_missing_required": models_missing_required,
        "models_enabled_total": models_enabled_total,
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
    max_confirm_timeouts: int | None,
    max_critical_misses: int | None,
    max_risk_latency_p90: int | None,
    max_risk_latency_max: int | None,
    max_ocr_cer: float | None,
    min_ocr_exact_match_rate: float | None,
    min_ocr_coverage: float | None,
    max_ocr_latency_p90: int | None,
    min_seg_f1_50: float | None,
    min_seg_coverage: float | None,
    min_seg_track_coverage: float | None,
    min_seg_tracks_total: int | None,
    max_seg_id_switches: int | None,
    min_depth_delta1: float | None,
    max_depth_absrel: float | None,
    min_depth_coverage: float | None,
    max_depth_latency_p90: int | None,
    min_costmap_coverage: float | None = None,
    max_costmap_latency_p90: int | None = None,
    max_costmap_dynamic_filter_rate_mean: float | None = None,
    min_costmap_fused_coverage: float | None = None,
    max_costmap_fused_latency_p90: int | None = None,
    min_costmap_fused_iou_p90: float | None = None,
    max_costmap_fused_flicker_rate_mean: float | None = None,
    max_costmap_fused_shift_gate_reject_rate: float | None = None,
    min_costmap_fused_shift_used_rate: float | None = None,
    min_slam_tracking_rate: float | None,
    max_slam_lost_rate: float | None,
    max_slam_latency_p90: int | None,
    max_slam_align_residual_p90: int | None,
    max_slam_ate_rmse: float | None,
    max_slam_rpe_trans_rmse: float | None,
    min_seg_mask_f1_50: float | None,
    min_seg_mask_coverage: float | None,
    max_seg_latency_p90: int | None,
    max_frame_e2e_p90: int | None,
    max_frame_e2e_max: int | None,
    max_frame_user_e2e_p90: int | None,
    max_frame_user_e2e_max: int | None,
    max_frame_user_e2e_tts_p90: int | None,
    max_frame_user_e2e_ar_p90: int | None,
    min_ack_kind_diversity: int | None,
    max_models_missing_required: int | None,
    max_seg_ctx_chars: int | None,
    max_seg_ctx_trunc_dropped: int | None,
    max_plan_req_seg_chars_p90: int | None,
    max_plan_req_seg_trunc_dropped: int | None,
    plan_req_fallback_used: str | None,
    min_plan_seg_ctx_coverage: float | None,
    min_plan_pov_ctx_coverage: float | None,
    min_plan_slam_ctx_coverage: float | None,
    require_plan_ctx_used: str | None,
    require_plan_slam_ctx_used: str | None,
    require_plan_costmap_ctx_used: str | None = None,
    max_plan_ctx_trunc_rate: float | None,
    min_plan_ctx_chars_p90: int | None,
    require_slam_ctx_present: str | None,
    max_slam_ctx_trunc_rate: float | None,
    min_slam_tracking_rate_mean: float | None,
    min_seg_prompt_text_chars: int | None,
    max_seg_prompt_trunc_rate: float | None,
    max_seg_prompt_trunc_dropped: int | None,
    has_pov: str | None,
    min_pov_decisions: int | None,
    has_pov_context: str | None,
    min_pov_context_token_approx: int | None,
    has_plan: str | None,
    plan_fallback_used: str | None,
    max_plan_latency_p90: int | None,
    max_plan_overcautious_rate: float | None,
    max_plan_guardrail_override_rate: float | None,
    max_plan_guardrails: int | None,
    min_plan_score: float | None,
    plan_risk_level: str | None,
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
    if max_confirm_timeouts is not None:
        if int(row.get("confirm_timeouts", 0) or 0) > int(max_confirm_timeouts):
            return False
    if max_critical_misses is not None:
        raw = row.get("critical_misses")
        value = int(raw) if isinstance(raw, int) else 0
        if value > int(max_critical_misses):
            return False
    if max_risk_latency_p90 is not None:
        value = row.get("risk_latency_p90")
        if value is None:
            return False
        if int(value) > int(max_risk_latency_p90):
            return False
    if max_risk_latency_max is not None:
        value = row.get("risk_latency_max")
        if value is None:
            return False
        if int(value) > int(max_risk_latency_max):
            return False
    if max_ocr_cer is not None:
        value = row.get("ocr_cer")
        if value is None:
            return False
        if float(value) > float(max_ocr_cer):
            return False
    if min_ocr_exact_match_rate is not None:
        value = row.get("ocr_exact_match_rate")
        if value is None:
            return False
        if float(value) < float(min_ocr_exact_match_rate):
            return False
    if min_ocr_coverage is not None:
        value = row.get("ocr_coverage")
        if value is None:
            return False
        if float(value) < float(min_ocr_coverage):
            return False
    if max_ocr_latency_p90 is not None:
        value = row.get("ocr_latency_p90")
        if value is None:
            return False
        if int(value) > int(max_ocr_latency_p90):
            return False
    if min_seg_f1_50 is not None:
        value = row.get("seg_f1_50")
        if value is None:
            return False
        if float(value) < float(min_seg_f1_50):
            return False
    if min_seg_coverage is not None:
        value = row.get("seg_coverage")
        if value is None:
            return False
        if float(value) < float(min_seg_coverage):
            return False
    if min_seg_track_coverage is not None:
        value = row.get("seg_track_coverage")
        if value is None:
            return False
        if float(value) < float(min_seg_track_coverage):
            return False
    if min_seg_tracks_total is not None:
        value = row.get("seg_tracks_total")
        if value is None:
            return False
        if int(value) < int(min_seg_tracks_total):
            return False
    if max_seg_id_switches is not None:
        value = row.get("seg_id_switches")
        if value is None:
            return False
        if int(value) > int(max_seg_id_switches):
            return False
    if min_depth_delta1 is not None:
        value = row.get("depth_delta1")
        if value is None:
            return False
        if float(value) < float(min_depth_delta1):
            return False
    if max_depth_absrel is not None:
        value = row.get("depth_absrel")
        if value is None:
            return False
        if float(value) > float(max_depth_absrel):
            return False
    if min_depth_coverage is not None:
        value = row.get("depth_coverage")
        if value is None:
            return False
        if float(value) < float(min_depth_coverage):
            return False
    if max_depth_latency_p90 is not None:
        value = row.get("depth_latency_p90")
        if value is None:
            return False
        if int(value) > int(max_depth_latency_p90):
            return False
    if min_costmap_coverage is not None:
        value = row.get("costmap_coverage")
        if value is None:
            return False
        if float(value) < float(min_costmap_coverage):
            return False
    if max_costmap_latency_p90 is not None:
        value = row.get("costmap_latency_p90")
        if value is None:
            return False
        if int(value) > int(max_costmap_latency_p90):
            return False
    if max_costmap_dynamic_filter_rate_mean is not None:
        value = row.get("costmap_dynamic_filter_rate_mean")
        if value is None:
            return False
        if float(value) > float(max_costmap_dynamic_filter_rate_mean):
            return False
    if min_costmap_fused_coverage is not None:
        value = row.get("costmap_fused_coverage")
        if value is None:
            return False
        if float(value) < float(min_costmap_fused_coverage):
            return False
    if max_costmap_fused_latency_p90 is not None:
        value = row.get("costmap_fused_latency_p90")
        if value is None:
            return False
        if int(value) > int(max_costmap_fused_latency_p90):
            return False
    if min_costmap_fused_iou_p90 is not None:
        value = row.get("costmap_fused_iou_p90")
        if value is None:
            return False
        if float(value) < float(min_costmap_fused_iou_p90):
            return False
    if max_costmap_fused_flicker_rate_mean is not None:
        value = row.get("costmap_fused_flicker_rate_mean")
        if value is None:
            return False
        if float(value) > float(max_costmap_fused_flicker_rate_mean):
            return False
    if max_costmap_fused_shift_gate_reject_rate is not None:
        value = row.get("costmap_fused_shift_gate_reject_rate")
        if value is None:
            return False
        if float(value) > float(max_costmap_fused_shift_gate_reject_rate):
            return False
    if min_costmap_fused_shift_used_rate is not None:
        value = row.get("costmap_fused_shift_used_rate")
        if value is None:
            return False
        if float(value) < float(min_costmap_fused_shift_used_rate):
            return False
    if min_slam_tracking_rate is not None:
        value = row.get("slam_tracking_rate")
        if value is None:
            return False
        if float(value) < float(min_slam_tracking_rate):
            return False
    if max_slam_lost_rate is not None:
        value = row.get("slam_lost_rate")
        if value is None:
            return False
        if float(value) > float(max_slam_lost_rate):
            return False
    if max_slam_latency_p90 is not None:
        value = row.get("slam_latency_p90")
        if value is None:
            return False
        if int(value) > int(max_slam_latency_p90):
            return False
    if max_slam_align_residual_p90 is not None:
        value = row.get("slam_align_residual_p90")
        if value is None:
            return False
        if int(value) > int(max_slam_align_residual_p90):
            return False
    if max_slam_ate_rmse is not None:
        value = row.get("slam_ate_rmse")
        if value is None:
            return False
        if float(value) > float(max_slam_ate_rmse):
            return False
    if max_slam_rpe_trans_rmse is not None:
        value = row.get("slam_rpe_trans_rmse")
        if value is None:
            return False
        if float(value) > float(max_slam_rpe_trans_rmse):
            return False
    if min_seg_mask_f1_50 is not None:
        value = row.get("seg_mask_f1_50")
        if value is None:
            return False
        if float(value) < float(min_seg_mask_f1_50):
            return False
    if min_seg_mask_coverage is not None:
        value = row.get("seg_mask_coverage")
        if value is None:
            return False
        if float(value) < float(min_seg_mask_coverage):
            return False
    if max_seg_latency_p90 is not None:
        value = row.get("seg_latency_p90")
        if value is None:
            return False
        if int(value) > int(max_seg_latency_p90):
            return False
    if max_frame_e2e_p90 is not None:
        value = row.get("frame_e2e_p90")
        if value is None:
            return False
        if int(value) > int(max_frame_e2e_p90):
            return False
    if max_frame_e2e_max is not None:
        value = row.get("frame_e2e_max")
        if value is None:
            return False
        if int(value) > int(max_frame_e2e_max):
            return False
    if max_frame_user_e2e_p90 is not None:
        value = row.get("frame_user_e2e_p90")
        if value is None:
            return False
        if int(value) > int(max_frame_user_e2e_p90):
            return False
    if max_frame_user_e2e_max is not None:
        value = row.get("frame_user_e2e_max")
        if value is None:
            return False
        if int(value) > int(max_frame_user_e2e_max):
            return False
    if max_frame_user_e2e_tts_p90 is not None:
        value = row.get("frame_user_e2e_tts_p90")
        if value is None:
            return False
        if int(value) > int(max_frame_user_e2e_tts_p90):
            return False
    if max_frame_user_e2e_ar_p90 is not None:
        value = row.get("frame_user_e2e_ar_p90")
        if value is None:
            return False
        if int(value) > int(max_frame_user_e2e_ar_p90):
            return False
    if min_ack_kind_diversity is not None:
        value = row.get("ack_kind_diversity")
        if value is None:
            return False
        if int(value) < int(min_ack_kind_diversity):
            return False
    if max_models_missing_required is not None:
        value = row.get("models_missing_required")
        if value is None:
            return False
        if int(value) > int(max_models_missing_required):
            return False
    if max_seg_ctx_chars is not None:
        value = row.get("seg_ctx_chars")
        if value is None:
            return False
        if int(value) > int(max_seg_ctx_chars):
            return False
    if max_seg_ctx_trunc_dropped is not None:
        value = row.get("seg_ctx_trunc_dropped")
        if value is None:
            return False
        if int(value) > int(max_seg_ctx_trunc_dropped):
            return False
    if max_plan_req_seg_chars_p90 is not None:
        value = row.get("plan_req_seg_chars_p90")
        if value is None:
            return False
        if int(value) > int(max_plan_req_seg_chars_p90):
            return False
    if max_plan_req_seg_trunc_dropped is not None:
        value = row.get("plan_req_seg_trunc_dropped")
        if value is None:
            return False
        if int(value) > int(max_plan_req_seg_trunc_dropped):
            return False
    if plan_req_fallback_used:
        normalized = plan_req_fallback_used.strip().lower()
        present = bool(row.get("plan_req_fallback_used"))
        if normalized in {"true", "1", "yes"} and not present:
            return False
        if normalized in {"false", "0", "no"} and present:
            return False
    if min_plan_seg_ctx_coverage is not None:
        value = row.get("plan_seg_ctx_coverage")
        if value is None:
            return False
        if float(value) < float(min_plan_seg_ctx_coverage):
            return False
    if min_plan_pov_ctx_coverage is not None:
        value = row.get("plan_pov_ctx_coverage")
        if value is None:
            return False
        if float(value) < float(min_plan_pov_ctx_coverage):
            return False
    if min_plan_slam_ctx_coverage is not None:
        value = row.get("plan_slam_ctx_coverage")
        if value is None:
            return False
        if float(value) < float(min_plan_slam_ctx_coverage):
            return False
    if require_plan_ctx_used:
        normalized = require_plan_ctx_used.strip().lower()
        present = bool(row.get("plan_ctx_used"))
        if normalized in {"true", "1", "yes"} and not present:
            return False
        if normalized in {"false", "0", "no"} and present:
            return False
    if require_plan_slam_ctx_used:
        normalized = require_plan_slam_ctx_used.strip().lower()
        used_rate = row.get("plan_slam_ctx_used_rate")
        present = bool(float(used_rate)) if isinstance(used_rate, (int, float)) else False
        if normalized in {"true", "1", "yes"} and not present:
            return False
        if normalized in {"false", "0", "no"} and present:
            return False
    if require_plan_costmap_ctx_used:
        normalized = require_plan_costmap_ctx_used.strip().lower()
        used_rate = row.get("plan_costmap_ctx_used_rate")
        present = bool(float(used_rate)) if isinstance(used_rate, (int, float)) else False
        if normalized in {"true", "1", "yes"} and not present:
            return False
        if normalized in {"false", "0", "no"} and present:
            return False
    if max_plan_ctx_trunc_rate is not None:
        value = row.get("plan_ctx_trunc_rate")
        if value is None:
            return False
        if float(value) > float(max_plan_ctx_trunc_rate):
            return False
    if min_plan_ctx_chars_p90 is not None:
        value = row.get("plan_ctx_chars_p90")
        if value is None:
            return False
        if int(value) < int(min_plan_ctx_chars_p90):
            return False
    if require_slam_ctx_present:
        normalized = require_slam_ctx_present.strip().lower()
        present = bool(row.get("slam_ctx_present"))
        if normalized in {"true", "1", "yes"} and not present:
            return False
        if normalized in {"false", "0", "no"} and present:
            return False
    if max_slam_ctx_trunc_rate is not None:
        value = row.get("slam_ctx_trunc_rate")
        if value is None:
            return False
        if float(value) > float(max_slam_ctx_trunc_rate):
            return False
    if min_slam_tracking_rate_mean is not None:
        value = row.get("slam_tracking_rate_mean")
        if value is None:
            return False
        if float(value) < float(min_slam_tracking_rate_mean):
            return False
    if min_seg_prompt_text_chars is not None:
        value = row.get("seg_prompt_text_chars_total")
        if value is None:
            return False
        if int(value) < int(min_seg_prompt_text_chars):
            return False
    if max_seg_prompt_trunc_rate is not None:
        value = row.get("seg_prompt_trunc_rate")
        if value is None:
            return False
        if float(value) > float(max_seg_prompt_trunc_rate):
            return False
    if max_seg_prompt_trunc_dropped is not None:
        value = row.get("seg_prompt_trunc_dropped")
        if value is None:
            return False
        if int(value) > int(max_seg_prompt_trunc_dropped):
            return False
    if has_pov:
        normalized = has_pov.strip().lower()
        present = bool(row.get("pov_present"))
        if normalized in {"true", "1", "yes"} and not present:
            return False
        if normalized in {"false", "0", "no"} and present:
            return False
    if min_pov_decisions is not None:
        if int(row.get("pov_decisions", 0) or 0) < int(min_pov_decisions):
            return False
    if has_pov_context:
        normalized = has_pov_context.strip().lower()
        present = bool(row.get("has_pov_context"))
        if normalized in {"true", "1", "yes"} and not present:
            return False
        if normalized in {"false", "0", "no"} and present:
            return False
    if min_pov_context_token_approx is not None:
        value = row.get("pov_context_token_approx")
        if value is None:
            return False
        if int(value) < int(min_pov_context_token_approx):
            return False
    if has_plan:
        normalized = has_plan.strip().lower()
        present = bool(row.get("plan_present"))
        if normalized in {"true", "1", "yes"} and not present:
            return False
        if normalized in {"false", "0", "no"} and present:
            return False
    if plan_fallback_used:
        normalized = plan_fallback_used.strip().lower()
        fallback_used = bool(row.get("plan_fallback_used"))
        if normalized in {"true", "1", "yes"} and not fallback_used:
            return False
        if normalized in {"false", "0", "no"} and fallback_used:
            return False
    if max_plan_latency_p90 is not None:
        value = row.get("plan_latency_p90")
        if value is None:
            return False
        if int(value) > int(max_plan_latency_p90):
            return False
    if max_plan_overcautious_rate is not None:
        value = row.get("plan_overcautious_rate")
        if value is None:
            return False
        if float(value) > float(max_plan_overcautious_rate):
            return False
    if max_plan_guardrail_override_rate is not None:
        value = row.get("plan_guardrail_override_rate")
        if value is None:
            return False
        if float(value) > float(max_plan_guardrail_override_rate):
            return False
    if max_plan_guardrails is not None:
        value = int(row.get("plan_guardrails", 0) or 0)
        if value > int(max_plan_guardrails):
            return False
    if min_plan_score is not None:
        value = row.get("plan_score")
        if value is None:
            return False
        if float(value) < float(min_plan_score):
            return False
    if plan_risk_level:
        expected = str(plan_risk_level).strip().lower()
        actual = str(row.get("plan_risk_level") or "").strip().lower()
        if actual != expected:
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
        "risk_latency_p90",
        "ocr_cer",
        "ocr_exact_match_rate",
        "ocr_coverage",
        "ocr_latency_p90",
        "seg_f1_50",
        "seg_latency_p90",
        "seg_coverage",
        "seg_track_coverage",
        "seg_tracks_total",
        "seg_id_switches",
        "depth_absrel",
        "depth_rmse",
        "depth_delta1",
        "depth_coverage",
        "depth_latency_p90",
        "costmap_coverage",
        "costmap_latency_p90",
        "costmap_density_mean",
        "costmap_dynamic_filter_rate_mean",
        "costmap_fused_coverage",
        "costmap_fused_latency_p90",
        "costmap_fused_iou_p90",
        "costmap_fused_flicker_rate_mean",
        "costmap_fused_shift_used_rate",
        "costmap_fused_shift_gate_reject_rate",
        "slam_tracking_rate",
        "slam_lost_rate",
        "slam_relocalized",
        "slam_latency_p90",
        "slam_ate_rmse",
        "slam_rpe_trans_rmse",
        "frame_e2e_p90",
        "frame_e2e_max",
        "frame_seg_p90",
        "frame_risk_p90",
        "frame_plan_p90",
        "frame_execute_p90",
        "frame_user_e2e_p90",
        "frame_user_e2e_max",
        "ack_coverage",
        "seg_mask_f1_50",
        "seg_mask_coverage",
        "seg_mask_mean_iou",
        "seg_ctx_chars",
        "seg_ctx_segments",
        "seg_ctx_trunc_dropped",
        "plan_req_seg_chars_p90",
        "plan_req_seg_trunc_dropped",
        "plan_req_pov_chars_p90",
        "plan_rule_applied",
        "plan_seg_ctx_coverage",
        "plan_pov_ctx_coverage",
        "plan_slam_ctx_coverage",
        "plan_slam_ctx_used_rate",
        "plan_costmap_ctx_coverage_p90",
        "plan_costmap_ctx_used_rate",
        "plan_ctx_used_rate",
        "plan_ctx_chars_p90",
        "plan_ctx_trunc_rate",
        "plan_ctx_seg_chars_p90",
        "plan_ctx_pov_chars_p90",
        "plan_ctx_risk_chars_p90",
        "slam_ctx_chars_p90",
        "slam_ctx_trunc_rate",
        "slam_tracking_rate_mean",
        "pov_decisions",
        "pov_token_approx",
        "pov_decision_per_min",
        "pov_context_token_approx",
        "seg_prompt_text_chars_total",
        "seg_prompt_chars_out",
        "seg_prompt_targets_out",
        "seg_prompt_trunc_dropped",
        "seg_prompt_trunc_rate",
        "plan_actions",
        "plan_guardrails",
        "plan_latency_p90",
        "confirm_timeouts",
        "plan_score",
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
    max_confirm_timeouts: int | None,
    max_critical_misses: int | None,
    max_risk_latency_p90: int | None,
    max_risk_latency_max: int | None,
    max_ocr_cer: float | None,
    min_ocr_exact_match_rate: float | None,
    min_ocr_coverage: float | None,
    max_ocr_latency_p90: int | None,
    min_seg_f1_50: float | None,
    min_seg_coverage: float | None,
    min_seg_track_coverage: float | None,
    min_seg_tracks_total: int | None,
    max_seg_id_switches: int | None,
    min_depth_delta1: float | None,
    max_depth_absrel: float | None,
    min_depth_coverage: float | None,
    max_depth_latency_p90: int | None,
    min_costmap_coverage: float | None,
    max_costmap_latency_p90: int | None,
    max_costmap_dynamic_filter_rate_mean: float | None,
    min_costmap_fused_coverage: float | None,
    max_costmap_fused_latency_p90: int | None,
    min_costmap_fused_iou_p90: float | None,
    max_costmap_fused_flicker_rate_mean: float | None,
    max_costmap_fused_shift_gate_reject_rate: float | None,
    min_costmap_fused_shift_used_rate: float | None,
    min_slam_tracking_rate: float | None,
    max_slam_lost_rate: float | None,
    max_slam_latency_p90: int | None,
    max_slam_align_residual_p90: int | None,
    max_slam_ate_rmse: float | None,
    max_slam_rpe_trans_rmse: float | None,
    min_seg_mask_f1_50: float | None,
    min_seg_mask_coverage: float | None,
    max_seg_latency_p90: int | None,
    max_frame_e2e_p90: int | None,
    max_frame_e2e_max: int | None,
    max_frame_user_e2e_p90: int | None,
    max_frame_user_e2e_max: int | None,
    max_frame_user_e2e_tts_p90: int | None,
    max_frame_user_e2e_ar_p90: int | None,
    min_ack_kind_diversity: int | None,
    max_models_missing_required: int | None,
    max_seg_ctx_chars: int | None,
    max_seg_ctx_trunc_dropped: int | None,
    max_plan_req_seg_chars_p90: int | None,
    max_plan_req_seg_trunc_dropped: int | None,
    plan_req_fallback_used: str | None,
    min_plan_seg_ctx_coverage: float | None,
    min_plan_pov_ctx_coverage: float | None,
    min_plan_slam_ctx_coverage: float | None,
    require_plan_ctx_used: str | None,
    require_plan_slam_ctx_used: str | None,
    require_plan_costmap_ctx_used: str | None,
    max_plan_ctx_trunc_rate: float | None,
    min_plan_ctx_chars_p90: int | None,
    require_slam_ctx_present: str | None,
    max_slam_ctx_trunc_rate: float | None,
    min_slam_tracking_rate_mean: float | None,
    min_seg_prompt_text_chars: int | None,
    max_seg_prompt_trunc_rate: float | None,
    max_seg_prompt_trunc_dropped: int | None,
    has_pov: str | None,
    min_pov_decisions: int | None,
    has_pov_context: str | None,
    min_pov_context_token_approx: int | None,
    has_plan: str | None,
    plan_fallback_used: str | None,
    max_plan_latency_p90: int | None,
    max_plan_overcautious_rate: float | None,
    max_plan_guardrail_override_rate: float | None,
    max_plan_guardrails: int | None,
    min_plan_score: float | None,
    plan_risk_level: str | None,
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
            max_confirm_timeouts=max_confirm_timeouts,
            max_critical_misses=max_critical_misses,
            max_risk_latency_p90=max_risk_latency_p90,
            max_risk_latency_max=max_risk_latency_max,
            max_ocr_cer=max_ocr_cer,
            min_ocr_exact_match_rate=min_ocr_exact_match_rate,
            min_ocr_coverage=min_ocr_coverage,
            max_ocr_latency_p90=max_ocr_latency_p90,
            min_seg_f1_50=min_seg_f1_50,
            min_seg_coverage=min_seg_coverage,
            min_seg_track_coverage=min_seg_track_coverage,
            min_seg_tracks_total=min_seg_tracks_total,
            max_seg_id_switches=max_seg_id_switches,
            min_depth_delta1=min_depth_delta1,
            max_depth_absrel=max_depth_absrel,
            min_depth_coverage=min_depth_coverage,
            max_depth_latency_p90=max_depth_latency_p90,
            min_costmap_coverage=min_costmap_coverage,
            max_costmap_latency_p90=max_costmap_latency_p90,
            max_costmap_dynamic_filter_rate_mean=max_costmap_dynamic_filter_rate_mean,
            min_costmap_fused_coverage=min_costmap_fused_coverage,
            max_costmap_fused_latency_p90=max_costmap_fused_latency_p90,
            min_costmap_fused_iou_p90=min_costmap_fused_iou_p90,
            max_costmap_fused_flicker_rate_mean=max_costmap_fused_flicker_rate_mean,
            max_costmap_fused_shift_gate_reject_rate=max_costmap_fused_shift_gate_reject_rate,
            min_costmap_fused_shift_used_rate=min_costmap_fused_shift_used_rate,
            min_slam_tracking_rate=min_slam_tracking_rate,
            max_slam_lost_rate=max_slam_lost_rate,
            max_slam_latency_p90=max_slam_latency_p90,
            max_slam_align_residual_p90=max_slam_align_residual_p90,
            max_slam_ate_rmse=max_slam_ate_rmse,
            max_slam_rpe_trans_rmse=max_slam_rpe_trans_rmse,
            min_seg_mask_f1_50=min_seg_mask_f1_50,
            min_seg_mask_coverage=min_seg_mask_coverage,
            max_seg_latency_p90=max_seg_latency_p90,
            max_frame_e2e_p90=max_frame_e2e_p90,
            max_frame_e2e_max=max_frame_e2e_max,
            max_frame_user_e2e_p90=max_frame_user_e2e_p90,
            max_frame_user_e2e_max=max_frame_user_e2e_max,
            max_frame_user_e2e_tts_p90=max_frame_user_e2e_tts_p90,
            max_frame_user_e2e_ar_p90=max_frame_user_e2e_ar_p90,
            min_ack_kind_diversity=min_ack_kind_diversity,
            max_models_missing_required=max_models_missing_required,
            max_seg_ctx_chars=max_seg_ctx_chars,
            max_seg_ctx_trunc_dropped=max_seg_ctx_trunc_dropped,
            max_plan_req_seg_chars_p90=max_plan_req_seg_chars_p90,
            max_plan_req_seg_trunc_dropped=max_plan_req_seg_trunc_dropped,
            plan_req_fallback_used=plan_req_fallback_used,
            min_plan_seg_ctx_coverage=min_plan_seg_ctx_coverage,
            min_plan_pov_ctx_coverage=min_plan_pov_ctx_coverage,
            min_plan_slam_ctx_coverage=min_plan_slam_ctx_coverage,
            require_plan_ctx_used=require_plan_ctx_used,
            require_plan_slam_ctx_used=require_plan_slam_ctx_used,
            require_plan_costmap_ctx_used=require_plan_costmap_ctx_used,
            max_plan_ctx_trunc_rate=max_plan_ctx_trunc_rate,
            min_plan_ctx_chars_p90=min_plan_ctx_chars_p90,
            require_slam_ctx_present=require_slam_ctx_present,
            max_slam_ctx_trunc_rate=max_slam_ctx_trunc_rate,
            min_slam_tracking_rate_mean=min_slam_tracking_rate_mean,
            min_seg_prompt_text_chars=min_seg_prompt_text_chars,
            max_seg_prompt_trunc_rate=max_seg_prompt_trunc_rate,
            max_seg_prompt_trunc_dropped=max_seg_prompt_trunc_dropped,
            has_pov=has_pov,
            min_pov_decisions=min_pov_decisions,
            has_pov_context=has_pov_context,
            min_pov_context_token_approx=min_pov_context_token_approx,
            has_plan=has_plan,
            plan_fallback_used=plan_fallback_used,
            max_plan_latency_p90=max_plan_latency_p90,
            max_plan_overcautious_rate=max_plan_overcautious_rate,
            max_plan_guardrail_override_rate=max_plan_guardrail_override_rate,
            max_plan_guardrails=max_plan_guardrails,
            min_plan_score=min_plan_score,
            plan_risk_level=plan_risk_level,
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
    max_confirm_timeouts: int | None = None,
    max_critical_misses: int | None = None,
    max_risk_latency_p90: int | None = None,
    max_risk_latency_max: int | None = None,
    max_ocr_cer: float | None = None,
    min_ocr_exact_match_rate: float | None = None,
    min_ocr_coverage: float | None = None,
    max_ocr_latency_p90: int | None = None,
    min_seg_f1_50: float | None = None,
    min_seg_coverage: float | None = None,
    min_seg_track_coverage: float | None = None,
    min_seg_tracks_total: int | None = None,
    max_seg_id_switches: int | None = None,
    min_depth_delta1: float | None = None,
    max_depth_absrel: float | None = None,
    min_depth_coverage: float | None = None,
    max_depth_latency_p90: int | None = None,
    min_costmap_coverage: float | None = None,
    max_costmap_latency_p90: int | None = None,
    max_costmap_dynamic_filter_rate_mean: float | None = None,
    min_costmap_fused_coverage: float | None = None,
    max_costmap_fused_latency_p90: int | None = None,
    min_costmap_fused_iou_p90: float | None = None,
    max_costmap_fused_flicker_rate_mean: float | None = None,
    max_costmap_fused_shift_gate_reject_rate: float | None = None,
    min_costmap_fused_shift_used_rate: float | None = None,
    min_slam_tracking_rate: float | None = None,
    max_slam_lost_rate: float | None = None,
    max_slam_latency_p90: int | None = None,
    max_slam_align_residual_p90: int | None = None,
    max_slam_ate_rmse: float | None = None,
    max_slam_rpe_trans_rmse: float | None = None,
    min_seg_mask_f1_50: float | None = None,
    min_seg_mask_coverage: float | None = None,
    max_seg_latency_p90: int | None = None,
    max_frame_e2e_p90: int | None = None,
    max_frame_e2e_max: int | None = None,
    max_frame_user_e2e_p90: int | None = None,
    max_frame_user_e2e_max: int | None = None,
    max_frame_user_e2e_tts_p90: int | None = None,
    max_frame_user_e2e_ar_p90: int | None = None,
    min_ack_kind_diversity: int | None = None,
    max_models_missing_required: int | None = None,
    max_seg_ctx_chars: int | None = None,
    max_seg_ctx_trunc_dropped: int | None = None,
    max_plan_req_seg_chars_p90: int | None = None,
    max_plan_req_seg_trunc_dropped: int | None = None,
    plan_req_fallback_used: str = "any",
    min_plan_seg_ctx_coverage: float | None = None,
    min_plan_pov_ctx_coverage: float | None = None,
    min_plan_slam_ctx_coverage: float | None = None,
    require_plan_ctx_used: str = "any",
    require_plan_slam_ctx_used: str = "any",
    max_plan_ctx_trunc_rate: float | None = None,
    min_plan_ctx_chars_p90: int | None = None,
    require_slam_ctx_present: str = "any",
    max_slam_ctx_trunc_rate: float | None = None,
    min_slam_tracking_rate_mean: float | None = None,
    min_seg_prompt_text_chars: int | None = None,
    max_seg_prompt_trunc_rate: float | None = None,
    max_seg_prompt_trunc_dropped: int | None = None,
    has_pov: str = "any",
    min_pov_decisions: int | None = None,
    has_pov_context: str = "any",
    min_pov_context_token_approx: int | None = None,
    has_plan: str = "any",
    plan_fallback_used: str = "any",
    max_plan_latency_p90: int | None = None,
    max_plan_overcautious_rate: float | None = None,
    max_plan_guardrail_override_rate: float | None = None,
    require_plan_costmap_ctx_used: str = "any",
    max_plan_guardrails: int | None = None,
    min_plan_score: float | None = None,
    plan_risk_level: str | None = None,
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
        max_confirm_timeouts=max_confirm_timeouts,
        max_critical_misses=max_critical_misses,
        max_risk_latency_p90=max_risk_latency_p90,
        max_risk_latency_max=max_risk_latency_max,
        max_ocr_cer=max_ocr_cer,
        min_ocr_exact_match_rate=min_ocr_exact_match_rate,
        min_ocr_coverage=min_ocr_coverage,
        max_ocr_latency_p90=max_ocr_latency_p90,
        min_seg_f1_50=min_seg_f1_50,
        min_seg_coverage=min_seg_coverage,
        min_seg_track_coverage=min_seg_track_coverage,
        min_seg_tracks_total=min_seg_tracks_total,
        max_seg_id_switches=max_seg_id_switches,
        min_depth_delta1=min_depth_delta1,
        max_depth_absrel=max_depth_absrel,
        min_depth_coverage=min_depth_coverage,
        max_depth_latency_p90=max_depth_latency_p90,
        min_costmap_coverage=min_costmap_coverage,
        max_costmap_latency_p90=max_costmap_latency_p90,
        max_costmap_dynamic_filter_rate_mean=max_costmap_dynamic_filter_rate_mean,
        min_costmap_fused_coverage=min_costmap_fused_coverage,
        max_costmap_fused_latency_p90=max_costmap_fused_latency_p90,
        min_costmap_fused_iou_p90=min_costmap_fused_iou_p90,
        max_costmap_fused_flicker_rate_mean=max_costmap_fused_flicker_rate_mean,
        max_costmap_fused_shift_gate_reject_rate=max_costmap_fused_shift_gate_reject_rate,
        min_costmap_fused_shift_used_rate=min_costmap_fused_shift_used_rate,
        min_slam_tracking_rate=min_slam_tracking_rate,
        max_slam_lost_rate=max_slam_lost_rate,
        max_slam_latency_p90=max_slam_latency_p90,
        max_slam_align_residual_p90=max_slam_align_residual_p90,
        max_slam_ate_rmse=max_slam_ate_rmse,
        max_slam_rpe_trans_rmse=max_slam_rpe_trans_rmse,
        min_seg_mask_f1_50=min_seg_mask_f1_50,
        min_seg_mask_coverage=min_seg_mask_coverage,
        max_seg_latency_p90=max_seg_latency_p90,
        max_frame_e2e_p90=max_frame_e2e_p90,
        max_frame_e2e_max=max_frame_e2e_max,
        max_frame_user_e2e_p90=max_frame_user_e2e_p90,
        max_frame_user_e2e_max=max_frame_user_e2e_max,
        max_frame_user_e2e_tts_p90=max_frame_user_e2e_tts_p90,
        max_frame_user_e2e_ar_p90=max_frame_user_e2e_ar_p90,
        min_ack_kind_diversity=min_ack_kind_diversity,
        max_models_missing_required=max_models_missing_required,
        max_seg_ctx_chars=max_seg_ctx_chars,
        max_seg_ctx_trunc_dropped=max_seg_ctx_trunc_dropped,
        max_plan_req_seg_chars_p90=max_plan_req_seg_chars_p90,
        max_plan_req_seg_trunc_dropped=max_plan_req_seg_trunc_dropped,
        plan_req_fallback_used=plan_req_fallback_used,
        min_plan_seg_ctx_coverage=min_plan_seg_ctx_coverage,
        min_plan_pov_ctx_coverage=min_plan_pov_ctx_coverage,
        min_plan_slam_ctx_coverage=min_plan_slam_ctx_coverage,
        require_plan_ctx_used=require_plan_ctx_used,
        require_plan_slam_ctx_used=require_plan_slam_ctx_used,
        max_plan_ctx_trunc_rate=max_plan_ctx_trunc_rate,
        min_plan_ctx_chars_p90=min_plan_ctx_chars_p90,
        require_slam_ctx_present=require_slam_ctx_present,
        max_slam_ctx_trunc_rate=max_slam_ctx_trunc_rate,
        min_slam_tracking_rate_mean=min_slam_tracking_rate_mean,
        min_seg_prompt_text_chars=min_seg_prompt_text_chars,
        max_seg_prompt_trunc_rate=max_seg_prompt_trunc_rate,
        max_seg_prompt_trunc_dropped=max_seg_prompt_trunc_dropped,
        has_pov=has_pov,
        min_pov_decisions=min_pov_decisions,
        has_pov_context=has_pov_context,
        min_pov_context_token_approx=min_pov_context_token_approx,
        has_plan=has_plan,
        plan_fallback_used=plan_fallback_used,
        max_plan_latency_p90=max_plan_latency_p90,
        max_plan_overcautious_rate=max_plan_overcautious_rate,
        max_plan_guardrail_override_rate=max_plan_guardrail_override_rate,
        require_plan_costmap_ctx_used=require_plan_costmap_ctx_used,
        max_plan_guardrails=max_plan_guardrails,
        min_plan_score=min_plan_score,
        plan_risk_level=plan_risk_level,
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
        confirm_timeouts = html.escape(str(row.get("confirm_timeouts", 0)))
        critical_misses_raw = row.get("critical_misses")
        critical_misses = "—" if critical_misses_raw is None else str(critical_misses_raw)
        max_delay_raw = row.get("max_delay_frames")
        max_delay = "—" if max_delay_raw is None else str(max_delay_raw)
        risk_p90_raw = row.get("risk_latency_p90")
        risk_p90 = "—" if risk_p90_raw is None else str(risk_p90_raw)
        ocr_cer_raw = row.get("ocr_cer")
        ocr_cer = "—" if ocr_cer_raw is None else f"{float(ocr_cer_raw):.4f}"
        ocr_exact_raw = row.get("ocr_exact_match_rate")
        ocr_exact = "—" if ocr_exact_raw is None else f"{float(ocr_exact_raw):.4f}"
        ocr_cov_raw = row.get("ocr_coverage")
        ocr_cov = "—" if ocr_cov_raw is None else f"{float(ocr_cov_raw):.4f}"
        ocr_p90_raw = row.get("ocr_latency_p90")
        ocr_p90 = "—" if ocr_p90_raw is None else str(int(ocr_p90_raw))
        frame_user_e2e_p90_raw = row.get("frame_user_e2e_p90")
        frame_user_e2e_p90 = "—" if frame_user_e2e_p90_raw is None else str(int(frame_user_e2e_p90_raw))
        frame_user_e2e_max_raw = row.get("frame_user_e2e_max")
        frame_user_e2e_max = "—" if frame_user_e2e_max_raw is None else str(int(frame_user_e2e_max_raw))
        frame_user_e2e_tts_p90_raw = row.get("frame_user_e2e_tts_p90")
        frame_user_e2e_tts_p90 = "—" if frame_user_e2e_tts_p90_raw is None else str(int(frame_user_e2e_tts_p90_raw))
        frame_user_e2e_tts_max_raw = row.get("frame_user_e2e_tts_max")
        frame_user_e2e_tts_max = "—" if frame_user_e2e_tts_max_raw is None else str(int(frame_user_e2e_tts_max_raw))
        frame_user_e2e_ar_p90_raw = row.get("frame_user_e2e_ar_p90")
        frame_user_e2e_ar_p90 = "—" if frame_user_e2e_ar_p90_raw is None else str(int(frame_user_e2e_ar_p90_raw))
        frame_user_e2e_ar_max_raw = row.get("frame_user_e2e_ar_max")
        frame_user_e2e_ar_max = "—" if frame_user_e2e_ar_max_raw is None else str(int(frame_user_e2e_ar_max_raw))
        ack_kind_diversity_raw = row.get("ack_kind_diversity")
        ack_kind_diversity = "—" if ack_kind_diversity_raw is None else str(int(ack_kind_diversity_raw))
        ack_coverage_raw = row.get("ack_coverage")
        ack_coverage = "—" if ack_coverage_raw is None else f"{float(ack_coverage_raw):.4f}"
        models_missing_required_raw = row.get("models_missing_required")
        models_missing_required = "—" if models_missing_required_raw is None else str(int(models_missing_required_raw))
        models_enabled_total_raw = row.get("models_enabled_total")
        models_enabled_total = "—" if models_enabled_total_raw is None else str(int(models_enabled_total_raw))
        seg_f1_raw = row.get("seg_f1_50")
        seg_f1 = "—" if seg_f1_raw is None else f"{float(seg_f1_raw):.4f}"
        seg_cov_raw = row.get("seg_coverage")
        seg_cov = "—" if seg_cov_raw is None else f"{float(seg_cov_raw):.4f}"
        seg_track_cov_raw = row.get("seg_track_coverage")
        seg_track_cov = "—" if seg_track_cov_raw is None else f"{float(seg_track_cov_raw):.4f}"
        seg_tracks_total_raw = row.get("seg_tracks_total")
        seg_tracks_total = "—" if seg_tracks_total_raw is None else str(int(seg_tracks_total_raw))
        seg_id_switches_raw = row.get("seg_id_switches")
        seg_id_switches = "—" if seg_id_switches_raw is None else str(int(seg_id_switches_raw))
        seg_mask_f1_raw = row.get("seg_mask_f1_50")
        seg_mask_f1 = "—" if seg_mask_f1_raw is None else f"{float(seg_mask_f1_raw):.4f}"
        seg_mask_cov_raw = row.get("seg_mask_coverage")
        seg_mask_cov = "—" if seg_mask_cov_raw is None else f"{float(seg_mask_cov_raw):.4f}"
        seg_mask_iou_raw = row.get("seg_mask_mean_iou")
        seg_mask_iou = "—" if seg_mask_iou_raw is None else f"{float(seg_mask_iou_raw):.4f}"
        seg_p90_raw = row.get("seg_latency_p90")
        seg_p90 = "—" if seg_p90_raw is None else str(int(seg_p90_raw))
        depth_absrel_raw = row.get("depth_absrel")
        depth_absrel = "—" if depth_absrel_raw is None else f"{float(depth_absrel_raw):.4f}"
        depth_rmse_raw = row.get("depth_rmse")
        depth_rmse = "—" if depth_rmse_raw is None else f"{float(depth_rmse_raw):.2f}"
        depth_delta1_raw = row.get("depth_delta1")
        depth_delta1 = "—" if depth_delta1_raw is None else f"{float(depth_delta1_raw):.4f}"
        depth_cov_raw = row.get("depth_coverage")
        depth_cov = "—" if depth_cov_raw is None else f"{float(depth_cov_raw):.4f}"
        depth_p90_raw = row.get("depth_latency_p90")
        depth_p90 = "—" if depth_p90_raw is None else str(int(depth_p90_raw))
        costmap_cov_raw = row.get("costmap_coverage")
        costmap_cov = "—" if costmap_cov_raw is None else f"{float(costmap_cov_raw):.4f}"
        costmap_p90_raw = row.get("costmap_latency_p90")
        costmap_p90 = "—" if costmap_p90_raw is None else str(int(costmap_p90_raw))
        costmap_density_raw = row.get("costmap_density_mean")
        costmap_density = "—" if costmap_density_raw is None else f"{float(costmap_density_raw):.4f}"
        costmap_dynamic_raw = row.get("costmap_dynamic_filter_rate_mean")
        costmap_dynamic = "—" if costmap_dynamic_raw is None else f"{float(costmap_dynamic_raw):.4f}"
        costmap_fused_cov_raw = row.get("costmap_fused_coverage")
        costmap_fused_cov = "—" if costmap_fused_cov_raw is None else f"{float(costmap_fused_cov_raw):.4f}"
        costmap_fused_latency_raw = row.get("costmap_fused_latency_p90")
        costmap_fused_latency = "—" if costmap_fused_latency_raw is None else str(int(costmap_fused_latency_raw))
        costmap_fused_iou_raw = row.get("costmap_fused_iou_p90")
        costmap_fused_iou = "—" if costmap_fused_iou_raw is None else f"{float(costmap_fused_iou_raw):.4f}"
        costmap_fused_flicker_raw = row.get("costmap_fused_flicker_rate_mean")
        costmap_fused_flicker = "—" if costmap_fused_flicker_raw is None else f"{float(costmap_fused_flicker_raw):.4f}"
        costmap_fused_shift_raw = row.get("costmap_fused_shift_used_rate")
        costmap_fused_shift = "—" if costmap_fused_shift_raw is None else f"{float(costmap_fused_shift_raw):.4f}"
        costmap_fused_shift_reject_raw = row.get("costmap_fused_shift_gate_reject_rate")
        costmap_fused_shift_reject = (
            "—" if costmap_fused_shift_reject_raw is None else f"{float(costmap_fused_shift_reject_raw):.4f}"
        )
        costmap_fused_shift_reason_raw = row.get("costmap_fused_shift_gate_top_reason")
        costmap_fused_shift_reason = "—" if costmap_fused_shift_reason_raw in {None, ""} else str(costmap_fused_shift_reason_raw)
        slam_tracking_rate_raw = row.get("slam_tracking_rate")
        slam_tracking_rate = "—" if slam_tracking_rate_raw is None else f"{float(slam_tracking_rate_raw):.4f}"
        slam_lost_rate_raw = row.get("slam_lost_rate")
        slam_lost_rate = "—" if slam_lost_rate_raw is None else f"{float(slam_lost_rate_raw):.4f}"
        slam_relocalized_raw = row.get("slam_relocalized")
        slam_relocalized = "—" if slam_relocalized_raw is None else str(int(slam_relocalized_raw))
        slam_p90_raw = row.get("slam_latency_p90")
        slam_p90 = "—" if slam_p90_raw is None else str(int(slam_p90_raw))
        slam_align_p90_raw = row.get("slam_align_residual_p90")
        slam_align_p90 = "—" if slam_align_p90_raw is None else str(int(slam_align_p90_raw))
        slam_align_mode_raw = row.get("slam_align_mode")
        slam_align_mode = "—" if slam_align_mode_raw in {None, ""} else str(slam_align_mode_raw)
        slam_ate_rmse_raw = row.get("slam_ate_rmse")
        slam_ate_rmse = "—" if slam_ate_rmse_raw is None else f"{float(slam_ate_rmse_raw):.4f}"
        slam_rpe_trans_rmse_raw = row.get("slam_rpe_trans_rmse")
        slam_rpe_trans_rmse = "—" if slam_rpe_trans_rmse_raw is None else f"{float(slam_rpe_trans_rmse_raw):.4f}"
        seg_ctx_chars_raw = row.get("seg_ctx_chars")
        seg_ctx_chars = "—" if seg_ctx_chars_raw is None else str(int(seg_ctx_chars_raw))
        seg_ctx_segments_raw = row.get("seg_ctx_segments")
        seg_ctx_segments = "—" if seg_ctx_segments_raw is None else str(int(seg_ctx_segments_raw))
        seg_ctx_trunc_raw = row.get("seg_ctx_trunc_dropped")
        seg_ctx_trunc = "—" if seg_ctx_trunc_raw is None else str(int(seg_ctx_trunc_raw))
        seg_prompt_present = "yes" if bool(row.get("seg_prompt_present")) else "no"
        seg_prompt_chars_raw = row.get("seg_prompt_text_chars_total")
        seg_prompt_chars = "—" if seg_prompt_chars_raw is None else str(int(seg_prompt_chars_raw))
        seg_prompt_chars_out_raw = row.get("seg_prompt_chars_out")
        seg_prompt_chars_out = "—" if seg_prompt_chars_out_raw is None else str(int(seg_prompt_chars_out_raw))
        seg_prompt_targets_out_raw = row.get("seg_prompt_targets_out")
        seg_prompt_targets_out = "—" if seg_prompt_targets_out_raw is None else str(int(seg_prompt_targets_out_raw))
        seg_prompt_trunc_dropped_raw = row.get("seg_prompt_trunc_dropped")
        seg_prompt_trunc_dropped = "—" if seg_prompt_trunc_dropped_raw is None else str(int(seg_prompt_trunc_dropped_raw))
        seg_prompt_trunc_rate_raw = row.get("seg_prompt_trunc_rate")
        seg_prompt_trunc_rate = "—" if seg_prompt_trunc_rate_raw is None else f"{float(seg_prompt_trunc_rate_raw):.4f}"
        pov_present = "yes" if bool(row.get("pov_present")) else "no"
        pov_decisions = str(int(row.get("pov_decisions", 0) or 0))
        pov_token_approx = str(int(row.get("pov_token_approx", 0) or 0))
        pov_dpm_raw = row.get("pov_decision_per_min")
        pov_dpm = "—" if pov_dpm_raw is None else f"{float(pov_dpm_raw):.3f}"
        pov_ctx_token_raw = row.get("pov_context_token_approx")
        pov_ctx_token = "—" if pov_ctx_token_raw is None else str(int(pov_ctx_token_raw))
        pov_ctx_chars_raw = row.get("pov_context_chars")
        pov_ctx_chars = "—" if pov_ctx_chars_raw is None else str(int(pov_ctx_chars_raw))
        plan_present = "yes" if bool(row.get("plan_present")) else "no"
        plan_risk_level = str(row.get("plan_risk_level") or "—")
        plan_actions = str(int(row.get("plan_actions", 0) or 0))
        plan_guardrails = str(int(row.get("plan_guardrails", 0) or 0))
        plan_has_stop = "yes" if bool(row.get("plan_has_stop")) else "no"
        plan_has_confirm = "yes" if bool(row.get("plan_has_confirm")) else "no"
        plan_score_raw = row.get("plan_score")
        plan_score = "—" if plan_score_raw is None else f"{float(plan_score_raw):.2f}"
        plan_fallback_used = "yes" if bool(row.get("plan_fallback_used")) else "no"
        plan_json_valid_raw = row.get("plan_json_valid")
        plan_json_valid = "—" if plan_json_valid_raw is None else ("true" if bool(plan_json_valid_raw) else "false")
        plan_prompt_version = str(row.get("plan_prompt_version") or "—")
        plan_latency_raw = row.get("plan_latency_p90")
        plan_latency = "—" if plan_latency_raw is None else str(int(plan_latency_raw))
        confirm_requests = str(int(row.get("confirm_requests", 0) or 0))
        overcautious_raw = row.get("plan_overcautious_rate")
        overcautious_rate = "—" if overcautious_raw is None else f"{float(overcautious_raw):.4f}"
        guardrail_override_raw = row.get("plan_guardrail_override_rate")
        guardrail_override_rate = "—" if guardrail_override_raw is None else f"{float(guardrail_override_raw):.4f}"
        plan_costmap_used_rate_raw = row.get("plan_costmap_ctx_used_rate")
        plan_costmap_used_rate = "—" if plan_costmap_used_rate_raw is None else f"{float(plan_costmap_used_rate_raw):.4f}"
        plan_costmap_coverage_raw = row.get("plan_costmap_ctx_coverage_p90")
        plan_costmap_coverage = "—" if plan_costmap_coverage_raw is None else f"{float(plan_costmap_coverage_raw):.4f}"
        rows_html += (
            "<tr>"
            f"<td><input type='checkbox' data-run-id='{run_val}' /></td>"
            f"<td><a href='{base_url}/runs/{run_val}'>{run_val}</a></td>"
            f"<td>{tag}</td>"
            f"<td>{created}</td>"
            f"<td>{safety}</td>"
            f"<td>{html.escape(quality)}</td>"
            f"<td>{confirm_timeouts}</td>"
            f"<td>{html.escape(critical_misses)}</td>"
            f"<td>{html.escape(max_delay)}</td>"
            f"<td>{html.escape(risk_p90)}</td>"
            f"<td>{html.escape(ocr_cer)}</td>"
            f"<td>{html.escape(ocr_exact)}</td>"
            f"<td>{html.escape(ocr_cov)}</td>"
            f"<td>{html.escape(ocr_p90)}</td>"
            f"<td>{html.escape(frame_user_e2e_p90)}</td>"
            f"<td>{html.escape(frame_user_e2e_max)}</td>"
            f"<td>{html.escape(frame_user_e2e_tts_p90)}</td>"
            f"<td>{html.escape(frame_user_e2e_tts_max)}</td>"
            f"<td>{html.escape(frame_user_e2e_ar_p90)}</td>"
            f"<td>{html.escape(frame_user_e2e_ar_max)}</td>"
            f"<td>{html.escape(ack_kind_diversity)}</td>"
            f"<td>{html.escape(ack_coverage)}</td>"
            f"<td>{html.escape(models_missing_required)}</td>"
            f"<td>{html.escape(models_enabled_total)}</td>"
            f"<td>{html.escape(seg_f1)}</td>"
            f"<td>{html.escape(seg_cov)}</td>"
            f"<td>{html.escape(seg_track_cov)}</td>"
            f"<td>{html.escape(seg_tracks_total)}</td>"
            f"<td>{html.escape(seg_id_switches)}</td>"
            f"<td>{html.escape(seg_mask_f1)}</td>"
            f"<td>{html.escape(seg_mask_cov)}</td>"
            f"<td>{html.escape(seg_mask_iou)}</td>"
            f"<td>{html.escape(seg_p90)}</td>"
            f"<td>{html.escape(depth_absrel)}</td>"
            f"<td>{html.escape(depth_rmse)}</td>"
            f"<td>{html.escape(depth_delta1)}</td>"
            f"<td>{html.escape(depth_cov)}</td>"
            f"<td>{html.escape(depth_p90)}</td>"
            f"<td>{html.escape(costmap_cov)}</td>"
            f"<td>{html.escape(costmap_p90)}</td>"
            f"<td>{html.escape(costmap_density)}</td>"
            f"<td>{html.escape(costmap_dynamic)}</td>"
            f"<td>{html.escape(costmap_fused_cov)}</td>"
            f"<td>{html.escape(costmap_fused_latency)}</td>"
            f"<td>{html.escape(costmap_fused_iou)}</td>"
            f"<td>{html.escape(costmap_fused_flicker)}</td>"
            f"<td>{html.escape(costmap_fused_shift)}</td>"
            f"<td>{html.escape(costmap_fused_shift_reject)}</td>"
            f"<td>{html.escape(costmap_fused_shift_reason)}</td>"
            f"<td>{html.escape(slam_tracking_rate)}</td>"
            f"<td>{html.escape(slam_lost_rate)}</td>"
            f"<td>{html.escape(slam_relocalized)}</td>"
            f"<td>{html.escape(slam_p90)}</td>"
            f"<td>{html.escape(slam_align_p90)}</td>"
            f"<td>{html.escape(slam_align_mode)}</td>"
            f"<td>{html.escape(slam_ate_rmse)}</td>"
            f"<td>{html.escape(slam_rpe_trans_rmse)}</td>"
            f"<td>{html.escape(seg_ctx_chars)}</td>"
            f"<td>{html.escape(seg_ctx_segments)}</td>"
            f"<td>{html.escape(seg_ctx_trunc)}</td>"
            f"<td>{html.escape(seg_prompt_present)}</td>"
            f"<td>{html.escape(seg_prompt_chars)}</td>"
            f"<td>{html.escape(seg_prompt_chars_out)}</td>"
            f"<td>{html.escape(seg_prompt_targets_out)}</td>"
            f"<td>{html.escape(seg_prompt_trunc_dropped)}</td>"
            f"<td>{html.escape(seg_prompt_trunc_rate)}</td>"
            f"<td>{html.escape(pov_present)}</td>"
            f"<td>{html.escape(pov_decisions)}</td>"
            f"<td>{html.escape(pov_token_approx)}</td>"
            f"<td>{html.escape(pov_dpm)}</td>"
            f"<td>{html.escape(pov_ctx_token)}</td>"
            f"<td>{html.escape(pov_ctx_chars)}</td>"
            f"<td>{html.escape(plan_present)}</td>"
            f"<td>{html.escape(plan_risk_level)}</td>"
            f"<td>{html.escape(plan_actions)}</td>"
            f"<td>{html.escape(plan_guardrails)}</td>"
            f"<td>{html.escape(plan_has_stop)}</td>"
            f"<td>{html.escape(plan_has_confirm)}</td>"
            f"<td>{html.escape(plan_score)}</td>"
            f"<td>{html.escape(plan_fallback_used)}</td>"
            f"<td>{html.escape(plan_json_valid)}</td>"
            f"<td>{html.escape(plan_prompt_version)}</td>"
            f"<td>{html.escape(plan_latency)}</td>"
            f"<td>{html.escape(confirm_requests)}</td>"
            f"<td>{html.escape(overcautious_rate)}</td>"
            f"<td>{html.escape(guardrail_override_rate)}</td>"
            f"<td>{html.escape(plan_costmap_coverage)}</td>"
            f"<td>{html.escape(plan_costmap_used_rate)}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html = "<tr><td colspan='99' class='muted'>no runs</td></tr>"

    scenario_value = html.escape(scenario or "")
    run_id_value = html.escape(run_id or "")
    sort_value = html.escape(sort or "createdAtMs")
    order_value = html.escape(order or "desc")
    limit_value = html.escape(str(limit))
    has_gt_value = html.escape(has_gt or "any")
    min_quality_value = html.escape("" if min_quality is None else str(min_quality))
    max_confirm_timeouts_value = html.escape("" if max_confirm_timeouts is None else str(max_confirm_timeouts))
    max_critical_misses_value = html.escape("" if max_critical_misses is None else str(max_critical_misses))
    max_risk_latency_p90_value = html.escape("" if max_risk_latency_p90 is None else str(max_risk_latency_p90))
    max_risk_latency_max_value = html.escape("" if max_risk_latency_max is None else str(max_risk_latency_max))
    max_ocr_cer_value = html.escape("" if max_ocr_cer is None else str(max_ocr_cer))
    min_ocr_exact_match_rate_value = html.escape("" if min_ocr_exact_match_rate is None else str(min_ocr_exact_match_rate))
    min_ocr_coverage_value = html.escape("" if min_ocr_coverage is None else str(min_ocr_coverage))
    max_ocr_latency_p90_value = html.escape("" if max_ocr_latency_p90 is None else str(max_ocr_latency_p90))
    min_seg_f1_50_value = html.escape("" if min_seg_f1_50 is None else str(min_seg_f1_50))
    min_seg_coverage_value = html.escape("" if min_seg_coverage is None else str(min_seg_coverage))
    min_seg_track_coverage_value = html.escape("" if min_seg_track_coverage is None else str(min_seg_track_coverage))
    min_seg_tracks_total_value = html.escape("" if min_seg_tracks_total is None else str(min_seg_tracks_total))
    max_seg_id_switches_value = html.escape("" if max_seg_id_switches is None else str(max_seg_id_switches))
    min_depth_delta1_value = html.escape("" if min_depth_delta1 is None else str(min_depth_delta1))
    max_depth_absrel_value = html.escape("" if max_depth_absrel is None else str(max_depth_absrel))
    min_depth_coverage_value = html.escape("" if min_depth_coverage is None else str(min_depth_coverage))
    max_depth_latency_p90_value = html.escape("" if max_depth_latency_p90 is None else str(max_depth_latency_p90))
    min_costmap_coverage_value = html.escape("" if min_costmap_coverage is None else str(min_costmap_coverage))
    max_costmap_latency_p90_value = html.escape("" if max_costmap_latency_p90 is None else str(max_costmap_latency_p90))
    max_costmap_dynamic_filter_rate_mean_value = html.escape(
        "" if max_costmap_dynamic_filter_rate_mean is None else str(max_costmap_dynamic_filter_rate_mean)
    )
    min_costmap_fused_coverage_value = html.escape(
        "" if min_costmap_fused_coverage is None else str(min_costmap_fused_coverage)
    )
    max_costmap_fused_latency_p90_value = html.escape(
        "" if max_costmap_fused_latency_p90 is None else str(max_costmap_fused_latency_p90)
    )
    min_costmap_fused_iou_p90_value = html.escape(
        "" if min_costmap_fused_iou_p90 is None else str(min_costmap_fused_iou_p90)
    )
    max_costmap_fused_flicker_rate_mean_value = html.escape(
        "" if max_costmap_fused_flicker_rate_mean is None else str(max_costmap_fused_flicker_rate_mean)
    )
    max_costmap_fused_shift_gate_reject_rate_value = html.escape(
        "" if max_costmap_fused_shift_gate_reject_rate is None else str(max_costmap_fused_shift_gate_reject_rate)
    )
    min_costmap_fused_shift_used_rate_value = html.escape(
        "" if min_costmap_fused_shift_used_rate is None else str(min_costmap_fused_shift_used_rate)
    )
    min_slam_tracking_rate_value = html.escape("" if min_slam_tracking_rate is None else str(min_slam_tracking_rate))
    max_slam_lost_rate_value = html.escape("" if max_slam_lost_rate is None else str(max_slam_lost_rate))
    max_slam_latency_p90_value = html.escape("" if max_slam_latency_p90 is None else str(max_slam_latency_p90))
    max_slam_align_residual_p90_value = html.escape(
        "" if max_slam_align_residual_p90 is None else str(max_slam_align_residual_p90)
    )
    max_slam_ate_rmse_value = html.escape("" if max_slam_ate_rmse is None else str(max_slam_ate_rmse))
    max_slam_rpe_trans_rmse_value = html.escape("" if max_slam_rpe_trans_rmse is None else str(max_slam_rpe_trans_rmse))
    min_seg_mask_f1_50_value = html.escape("" if min_seg_mask_f1_50 is None else str(min_seg_mask_f1_50))
    min_seg_mask_coverage_value = html.escape("" if min_seg_mask_coverage is None else str(min_seg_mask_coverage))
    max_seg_latency_p90_value = html.escape("" if max_seg_latency_p90 is None else str(max_seg_latency_p90))
    max_frame_user_e2e_p90_value = html.escape("" if max_frame_user_e2e_p90 is None else str(max_frame_user_e2e_p90))
    max_frame_user_e2e_max_value = html.escape("" if max_frame_user_e2e_max is None else str(max_frame_user_e2e_max))
    max_frame_user_e2e_tts_p90_value = html.escape(
        "" if max_frame_user_e2e_tts_p90 is None else str(max_frame_user_e2e_tts_p90)
    )
    max_frame_user_e2e_ar_p90_value = html.escape(
        "" if max_frame_user_e2e_ar_p90 is None else str(max_frame_user_e2e_ar_p90)
    )
    min_ack_kind_diversity_value = html.escape(
        "" if min_ack_kind_diversity is None else str(min_ack_kind_diversity)
    )
    max_models_missing_required_value = html.escape(
        "" if max_models_missing_required is None else str(max_models_missing_required)
    )
    max_seg_ctx_chars_value = html.escape("" if max_seg_ctx_chars is None else str(max_seg_ctx_chars))
    max_seg_ctx_trunc_dropped_value = html.escape(
        "" if max_seg_ctx_trunc_dropped is None else str(max_seg_ctx_trunc_dropped)
    )
    max_plan_ctx_trunc_rate_value = html.escape(
        "" if max_plan_ctx_trunc_rate is None else str(max_plan_ctx_trunc_rate)
    )
    min_plan_ctx_chars_p90_value = html.escape("" if min_plan_ctx_chars_p90 is None else str(min_plan_ctx_chars_p90))
    min_seg_prompt_text_chars_value = html.escape("" if min_seg_prompt_text_chars is None else str(min_seg_prompt_text_chars))
    max_seg_prompt_trunc_rate_value = html.escape(
        "" if max_seg_prompt_trunc_rate is None else str(max_seg_prompt_trunc_rate)
    )
    max_seg_prompt_trunc_dropped_value = html.escape(
        "" if max_seg_prompt_trunc_dropped is None else str(max_seg_prompt_trunc_dropped)
    )
    has_pov_value = html.escape(has_pov or "any")
    min_pov_decisions_value = html.escape("" if min_pov_decisions is None else str(min_pov_decisions))
    has_pov_context_value = html.escape(has_pov_context or "any")
    min_pov_context_token_approx_value = html.escape(
        "" if min_pov_context_token_approx is None else str(min_pov_context_token_approx)
    )
    has_plan_value = html.escape(has_plan or "any")
    plan_fallback_used_value = html.escape(plan_fallback_used or "any")
    max_plan_latency_p90_value = html.escape("" if max_plan_latency_p90 is None else str(max_plan_latency_p90))
    max_plan_overcautious_rate_value = html.escape(
        "" if max_plan_overcautious_rate is None else str(max_plan_overcautious_rate)
    )
    max_plan_guardrail_override_rate_value = html.escape(
        "" if max_plan_guardrail_override_rate is None else str(max_plan_guardrail_override_rate)
    )
    require_plan_costmap_ctx_used_value = html.escape(require_plan_costmap_ctx_used or "any")
    max_plan_guardrails_value = html.escape("" if max_plan_guardrails is None else str(max_plan_guardrails))
    min_plan_score_value = html.escape("" if min_plan_score is None else str(min_plan_score))
    plan_risk_level_value = html.escape(plan_risk_level or "")
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
      <label>has_pov:
        <select name="has_pov">
          <option value="any" {"selected" if has_pov_value == "any" else ""}>any</option>
          <option value="true" {"selected" if has_pov_value == "true" else ""}>true</option>
          <option value="false" {"selected" if has_pov_value == "false" else ""}>false</option>
        </select>
      </label>
      <label>has_pov_context:
        <select name="has_pov_context">
          <option value="any" {"selected" if has_pov_context_value == "any" else ""}>any</option>
          <option value="true" {"selected" if has_pov_context_value == "true" else ""}>true</option>
          <option value="false" {"selected" if has_pov_context_value == "false" else ""}>false</option>
        </select>
      </label>
      <label>has_plan:
        <select name="has_plan">
          <option value="any" {"selected" if has_plan_value == "any" else ""}>any</option>
          <option value="true" {"selected" if has_plan_value == "true" else ""}>true</option>
          <option value="false" {"selected" if has_plan_value == "false" else ""}>false</option>
        </select>
      </label>
      <label>plan_fallback_used:
        <select name="plan_fallback_used">
          <option value="any" {"selected" if plan_fallback_used_value == "any" else ""}>any</option>
          <option value="true" {"selected" if plan_fallback_used_value == "true" else ""}>true</option>
          <option value="false" {"selected" if plan_fallback_used_value == "false" else ""}>false</option>
        </select>
      </label>
      <label>min_quality: <input type="number" step="0.01" name="min_quality" value="{min_quality_value}" /></label>
      <label>min_pov_decisions: <input type="number" min="0" name="min_pov_decisions" value="{min_pov_decisions_value}" /></label>
      <label>min_pov_context_token_approx: <input type="number" min="0" name="min_pov_context_token_approx" value="{min_pov_context_token_approx_value}" /></label>
      <label>max_confirm_timeouts: <input type="number" min="0" name="max_confirm_timeouts" value="{max_confirm_timeouts_value}" /></label>
      <label>max_critical_misses: <input type="number" min="0" name="max_critical_misses" value="{max_critical_misses_value}" /></label>
      <label>max_risk_latency_p90: <input type="number" min="0" name="max_risk_latency_p90" value="{max_risk_latency_p90_value}" /></label>
      <label>max_risk_latency_max: <input type="number" min="0" name="max_risk_latency_max" value="{max_risk_latency_max_value}" /></label>
      <label>max_ocr_cer: <input type="number" step="0.0001" min="0" name="max_ocr_cer" value="{max_ocr_cer_value}" /></label>
      <label>min_ocr_exact_match_rate: <input type="number" step="0.0001" min="0" max="1" name="min_ocr_exact_match_rate" value="{min_ocr_exact_match_rate_value}" /></label>
      <label>min_ocr_coverage: <input type="number" step="0.0001" min="0" max="1" name="min_ocr_coverage" value="{min_ocr_coverage_value}" /></label>
      <label>max_ocr_latency_p90: <input type="number" min="0" name="max_ocr_latency_p90" value="{max_ocr_latency_p90_value}" /></label>
      <label>max_frame_user_e2e_p90: <input type="number" min="0" name="max_frame_user_e2e_p90" value="{max_frame_user_e2e_p90_value}" /></label>
      <label>max_frame_user_e2e_max: <input type="number" min="0" name="max_frame_user_e2e_max" value="{max_frame_user_e2e_max_value}" /></label>
      <label>max_frame_user_e2e_tts_p90: <input type="number" min="0" name="max_frame_user_e2e_tts_p90" value="{max_frame_user_e2e_tts_p90_value}" /></label>
      <label>max_frame_user_e2e_ar_p90: <input type="number" min="0" name="max_frame_user_e2e_ar_p90" value="{max_frame_user_e2e_ar_p90_value}" /></label>
      <label>min_ack_kind_diversity: <input type="number" min="0" name="min_ack_kind_diversity" value="{min_ack_kind_diversity_value}" /></label>
      <label>max_models_missing_required: <input type="number" min="0" name="max_models_missing_required" value="{max_models_missing_required_value}" /></label>
      <label>min_seg_f1_50: <input type="number" step="0.0001" min="0" max="1" name="min_seg_f1_50" value="{min_seg_f1_50_value}" /></label>
      <label>min_seg_coverage: <input type="number" step="0.0001" min="0" max="1" name="min_seg_coverage" value="{min_seg_coverage_value}" /></label>
      <label>min_seg_track_coverage: <input type="number" step="0.0001" min="0" max="1" name="min_seg_track_coverage" value="{min_seg_track_coverage_value}" /></label>
      <label>min_seg_tracks_total: <input type="number" step="1" min="0" name="min_seg_tracks_total" value="{min_seg_tracks_total_value}" /></label>
      <label>max_seg_id_switches: <input type="number" step="1" min="0" name="max_seg_id_switches" value="{max_seg_id_switches_value}" /></label>
      <label>min_depth_delta1: <input type="number" step="0.0001" min="0" max="1" name="min_depth_delta1" value="{min_depth_delta1_value}" /></label>
      <label>max_depth_absrel: <input type="number" step="0.0001" min="0" name="max_depth_absrel" value="{max_depth_absrel_value}" /></label>
      <label>min_depth_coverage: <input type="number" step="0.0001" min="0" max="1" name="min_depth_coverage" value="{min_depth_coverage_value}" /></label>
      <label>max_depth_latency_p90: <input type="number" min="0" name="max_depth_latency_p90" value="{max_depth_latency_p90_value}" /></label>
      <label>min_costmap_coverage: <input type="number" step="0.0001" min="0" max="1" name="min_costmap_coverage" value="{min_costmap_coverage_value}" /></label>
      <label>max_costmap_latency_p90: <input type="number" min="0" name="max_costmap_latency_p90" value="{max_costmap_latency_p90_value}" /></label>
      <label>max_costmap_dynamic_filter_rate_mean: <input type="number" step="0.0001" min="0" max="1" name="max_costmap_dynamic_filter_rate_mean" value="{max_costmap_dynamic_filter_rate_mean_value}" /></label>
      <label>min_costmap_fused_coverage: <input type="number" step="0.0001" min="0" max="1" name="min_costmap_fused_coverage" value="{min_costmap_fused_coverage_value}" /></label>
      <label>max_costmap_fused_latency_p90: <input type="number" min="0" name="max_costmap_fused_latency_p90" value="{max_costmap_fused_latency_p90_value}" /></label>
      <label>min_costmap_fused_iou_p90: <input type="number" step="0.0001" min="0" max="1" name="min_costmap_fused_iou_p90" value="{min_costmap_fused_iou_p90_value}" /></label>
      <label>max_costmap_fused_flicker_rate_mean: <input type="number" step="0.0001" min="0" max="1" name="max_costmap_fused_flicker_rate_mean" value="{max_costmap_fused_flicker_rate_mean_value}" /></label>
      <label>max_costmap_fused_shift_gate_reject_rate: <input type="number" step="0.0001" min="0" max="1" name="max_costmap_fused_shift_gate_reject_rate" value="{max_costmap_fused_shift_gate_reject_rate_value}" /></label>
      <label>min_costmap_fused_shift_used_rate: <input type="number" step="0.0001" min="0" max="1" name="min_costmap_fused_shift_used_rate" value="{min_costmap_fused_shift_used_rate_value}" /></label>
      <label>min_slam_tracking_rate: <input type="number" step="0.0001" min="0" max="1" name="min_slam_tracking_rate" value="{min_slam_tracking_rate_value}" /></label>
      <label>max_slam_lost_rate: <input type="number" step="0.0001" min="0" max="1" name="max_slam_lost_rate" value="{max_slam_lost_rate_value}" /></label>
      <label>max_slam_latency_p90: <input type="number" min="0" name="max_slam_latency_p90" value="{max_slam_latency_p90_value}" /></label>
      <label>max_slam_align_residual_p90: <input type="number" min="0" name="max_slam_align_residual_p90" value="{max_slam_align_residual_p90_value}" /></label>
      <label>max_slam_ate_rmse: <input type="number" step="0.0001" min="0" name="max_slam_ate_rmse" value="{max_slam_ate_rmse_value}" /></label>
      <label>max_slam_rpe_trans_rmse: <input type="number" step="0.0001" min="0" name="max_slam_rpe_trans_rmse" value="{max_slam_rpe_trans_rmse_value}" /></label>
      <label>min_seg_mask_f1_50: <input type="number" step="0.0001" min="0" max="1" name="min_seg_mask_f1_50" value="{min_seg_mask_f1_50_value}" /></label>
      <label>min_seg_mask_coverage: <input type="number" step="0.0001" min="0" max="1" name="min_seg_mask_coverage" value="{min_seg_mask_coverage_value}" /></label>
      <label>max_seg_latency_p90: <input type="number" min="0" name="max_seg_latency_p90" value="{max_seg_latency_p90_value}" /></label>
      <label>max_seg_ctx_chars: <input type="number" min="0" name="max_seg_ctx_chars" value="{max_seg_ctx_chars_value}" /></label>
      <label>max_seg_ctx_trunc_dropped: <input type="number" min="0" name="max_seg_ctx_trunc_dropped" value="{max_seg_ctx_trunc_dropped_value}" /></label>
      <label>max_plan_ctx_trunc_rate: <input type="number" step="0.0001" min="0" max="1" name="max_plan_ctx_trunc_rate" value="{max_plan_ctx_trunc_rate_value}" /></label>
      <label>min_plan_ctx_chars_p90: <input type="number" min="0" name="min_plan_ctx_chars_p90" value="{min_plan_ctx_chars_p90_value}" /></label>
      <label>min_seg_prompt_text_chars: <input type="number" min="0" name="min_seg_prompt_text_chars" value="{min_seg_prompt_text_chars_value}" /></label>
      <label>max_seg_prompt_trunc_rate: <input type="number" step="0.0001" min="0" max="1" name="max_seg_prompt_trunc_rate" value="{max_seg_prompt_trunc_rate_value}" /></label>
      <label>max_seg_prompt_trunc_dropped: <input type="number" min="0" name="max_seg_prompt_trunc_dropped" value="{max_seg_prompt_trunc_dropped_value}" /></label>
      <label>max_plan_guardrails: <input type="number" min="0" name="max_plan_guardrails" value="{max_plan_guardrails_value}" /></label>
      <label>max_plan_latency_p90: <input type="number" min="0" name="max_plan_latency_p90" value="{max_plan_latency_p90_value}" /></label>
      <label>max_plan_overcautious_rate: <input type="number" step="0.0001" min="0" max="1" name="max_plan_overcautious_rate" value="{max_plan_overcautious_rate_value}" /></label>
      <label>max_plan_guardrail_override_rate: <input type="number" step="0.0001" min="0" max="1" name="max_plan_guardrail_override_rate" value="{max_plan_guardrail_override_rate_value}" /></label>
      <label>require_plan_costmap_ctx_used:
        <select name="require_plan_costmap_ctx_used">
          <option value="any" {"selected" if require_plan_costmap_ctx_used_value == "any" else ""}>any</option>
          <option value="true" {"selected" if require_plan_costmap_ctx_used_value == "true" else ""}>true</option>
          <option value="false" {"selected" if require_plan_costmap_ctx_used_value == "false" else ""}>false</option>
        </select>
      </label>
      <label>min_plan_score: <input type="number" step="0.01" min="0" max="100" name="min_plan_score" value="{min_plan_score_value}" /></label>
      <label>plan_risk_level:
        <select name="plan_risk_level">
          <option value="" {"selected" if plan_risk_level_value == "" else ""}>any</option>
          <option value="low" {"selected" if plan_risk_level_value == "low" else ""}>low</option>
          <option value="medium" {"selected" if plan_risk_level_value == "medium" else ""}>medium</option>
          <option value="high" {"selected" if plan_risk_level_value == "high" else ""}>high</option>
          <option value="critical" {"selected" if plan_risk_level_value == "critical" else ""}>critical</option>
        </select>
      </label>
      <label>sort:
        <select name="sort">
          <option value="createdAtMs" {"selected" if sort_value == "createdAtMs" else ""}>createdAtMs</option>
          <option value="safety_score" {"selected" if sort_value == "safety_score" else ""}>safety_score</option>
          <option value="quality" {"selected" if sort_value == "quality" else ""}>quality</option>
          <option value="risk_latency_p90" {"selected" if sort_value == "risk_latency_p90" else ""}>risk_latency_p90</option>
          <option value="ocr_cer" {"selected" if sort_value == "ocr_cer" else ""}>ocr_cer</option>
          <option value="ocr_exact_match_rate" {"selected" if sort_value == "ocr_exact_match_rate" else ""}>ocr_exact_match_rate</option>
          <option value="ocr_coverage" {"selected" if sort_value == "ocr_coverage" else ""}>ocr_coverage</option>
          <option value="ocr_latency_p90" {"selected" if sort_value == "ocr_latency_p90" else ""}>ocr_latency_p90</option>
          <option value="frame_user_e2e_p90" {"selected" if sort_value == "frame_user_e2e_p90" else ""}>frame_user_e2e_p90</option>
          <option value="frame_user_e2e_max" {"selected" if sort_value == "frame_user_e2e_max" else ""}>frame_user_e2e_max</option>
          <option value="frame_user_e2e_tts_p90" {"selected" if sort_value == "frame_user_e2e_tts_p90" else ""}>frame_user_e2e_tts_p90</option>
          <option value="frame_user_e2e_ar_p90" {"selected" if sort_value == "frame_user_e2e_ar_p90" else ""}>frame_user_e2e_ar_p90</option>
          <option value="ack_kind_diversity" {"selected" if sort_value == "ack_kind_diversity" else ""}>ack_kind_diversity</option>
          <option value="ack_coverage" {"selected" if sort_value == "ack_coverage" else ""}>ack_coverage</option>
          <option value="models_missing_required" {"selected" if sort_value == "models_missing_required" else ""}>models_missing_required</option>
          <option value="models_enabled_total" {"selected" if sort_value == "models_enabled_total" else ""}>models_enabled_total</option>
          <option value="seg_f1_50" {"selected" if sort_value == "seg_f1_50" else ""}>seg_f1_50</option>
          <option value="seg_coverage" {"selected" if sort_value == "seg_coverage" else ""}>seg_coverage</option>
          <option value="seg_track_coverage" {"selected" if sort_value == "seg_track_coverage" else ""}>seg_track_coverage</option>
          <option value="seg_tracks_total" {"selected" if sort_value == "seg_tracks_total" else ""}>seg_tracks_total</option>
          <option value="seg_id_switches" {"selected" if sort_value == "seg_id_switches" else ""}>seg_id_switches</option>
          <option value="depth_absrel" {"selected" if sort_value == "depth_absrel" else ""}>depth_absrel</option>
          <option value="depth_rmse" {"selected" if sort_value == "depth_rmse" else ""}>depth_rmse</option>
          <option value="depth_delta1" {"selected" if sort_value == "depth_delta1" else ""}>depth_delta1</option>
          <option value="depth_coverage" {"selected" if sort_value == "depth_coverage" else ""}>depth_coverage</option>
          <option value="depth_latency_p90" {"selected" if sort_value == "depth_latency_p90" else ""}>depth_latency_p90</option>
          <option value="costmap_coverage" {"selected" if sort_value == "costmap_coverage" else ""}>costmap_coverage</option>
          <option value="costmap_latency_p90" {"selected" if sort_value == "costmap_latency_p90" else ""}>costmap_latency_p90</option>
          <option value="costmap_density_mean" {"selected" if sort_value == "costmap_density_mean" else ""}>costmap_density_mean</option>
          <option value="costmap_dynamic_filter_rate_mean" {"selected" if sort_value == "costmap_dynamic_filter_rate_mean" else ""}>costmap_dynamic_filter_rate_mean</option>
          <option value="costmap_fused_coverage" {"selected" if sort_value == "costmap_fused_coverage" else ""}>costmap_fused_coverage</option>
          <option value="costmap_fused_latency_p90" {"selected" if sort_value == "costmap_fused_latency_p90" else ""}>costmap_fused_latency_p90</option>
          <option value="costmap_fused_iou_p90" {"selected" if sort_value == "costmap_fused_iou_p90" else ""}>costmap_fused_iou_p90</option>
          <option value="costmap_fused_flicker_rate_mean" {"selected" if sort_value == "costmap_fused_flicker_rate_mean" else ""}>costmap_fused_flicker_rate_mean</option>
          <option value="costmap_fused_shift_used_rate" {"selected" if sort_value == "costmap_fused_shift_used_rate" else ""}>costmap_fused_shift_used_rate</option>
          <option value="costmap_fused_shift_gate_reject_rate" {"selected" if sort_value == "costmap_fused_shift_gate_reject_rate" else ""}>costmap_fused_shift_gate_reject_rate</option>
          <option value="slam_tracking_rate" {"selected" if sort_value == "slam_tracking_rate" else ""}>slam_tracking_rate</option>
          <option value="slam_lost_rate" {"selected" if sort_value == "slam_lost_rate" else ""}>slam_lost_rate</option>
          <option value="slam_latency_p90" {"selected" if sort_value == "slam_latency_p90" else ""}>slam_latency_p90</option>
          <option value="slam_align_residual_p90" {"selected" if sort_value == "slam_align_residual_p90" else ""}>slam_align_residual_p90</option>
          <option value="slam_ate_rmse" {"selected" if sort_value == "slam_ate_rmse" else ""}>slam_ate_rmse</option>
          <option value="slam_rpe_trans_rmse" {"selected" if sort_value == "slam_rpe_trans_rmse" else ""}>slam_rpe_trans_rmse</option>
          <option value="slam_align_mode" {"selected" if sort_value == "slam_align_mode" else ""}>slam_align_mode</option>
          <option value="seg_mask_f1_50" {"selected" if sort_value == "seg_mask_f1_50" else ""}>seg_mask_f1_50</option>
          <option value="seg_mask_coverage" {"selected" if sort_value == "seg_mask_coverage" else ""}>seg_mask_coverage</option>
          <option value="seg_mask_mean_iou" {"selected" if sort_value == "seg_mask_mean_iou" else ""}>seg_mask_mean_iou</option>
          <option value="seg_latency_p90" {"selected" if sort_value == "seg_latency_p90" else ""}>seg_latency_p90</option>
          <option value="seg_ctx_chars" {"selected" if sort_value == "seg_ctx_chars" else ""}>seg_ctx_chars</option>
          <option value="seg_ctx_segments" {"selected" if sort_value == "seg_ctx_segments" else ""}>seg_ctx_segments</option>
          <option value="seg_ctx_trunc_dropped" {"selected" if sort_value == "seg_ctx_trunc_dropped" else ""}>seg_ctx_trunc_dropped</option>
          <option value="plan_ctx_chars_p90" {"selected" if sort_value == "plan_ctx_chars_p90" else ""}>plan_ctx_chars_p90</option>
          <option value="plan_ctx_trunc_rate" {"selected" if sort_value == "plan_ctx_trunc_rate" else ""}>plan_ctx_trunc_rate</option>
          <option value="seg_prompt_text_chars_total" {"selected" if sort_value == "seg_prompt_text_chars_total" else ""}>seg_prompt_text_chars_total</option>
          <option value="seg_prompt_chars_out" {"selected" if sort_value == "seg_prompt_chars_out" else ""}>seg_prompt_chars_out</option>
          <option value="seg_prompt_targets_out" {"selected" if sort_value == "seg_prompt_targets_out" else ""}>seg_prompt_targets_out</option>
          <option value="seg_prompt_trunc_dropped" {"selected" if sort_value == "seg_prompt_trunc_dropped" else ""}>seg_prompt_trunc_dropped</option>
          <option value="seg_prompt_trunc_rate" {"selected" if sort_value == "seg_prompt_trunc_rate" else ""}>seg_prompt_trunc_rate</option>
          <option value="pov_decisions" {"selected" if sort_value == "pov_decisions" else ""}>pov_decisions</option>
          <option value="pov_token_approx" {"selected" if sort_value == "pov_token_approx" else ""}>pov_token_approx</option>
          <option value="pov_decision_per_min" {"selected" if sort_value == "pov_decision_per_min" else ""}>pov_decision_per_min</option>
          <option value="pov_context_token_approx" {"selected" if sort_value == "pov_context_token_approx" else ""}>pov_context_token_approx</option>
          <option value="plan_actions" {"selected" if sort_value == "plan_actions" else ""}>plan_actions</option>
          <option value="plan_guardrails" {"selected" if sort_value == "plan_guardrails" else ""}>plan_guardrails</option>
          <option value="plan_latency_p90" {"selected" if sort_value == "plan_latency_p90" else ""}>plan_latency_p90</option>
          <option value="confirm_timeouts" {"selected" if sort_value == "confirm_timeouts" else ""}>confirm_timeouts</option>
          <option value="plan_costmap_ctx_coverage_p90" {"selected" if sort_value == "plan_costmap_ctx_coverage_p90" else ""}>plan_costmap_ctx_coverage_p90</option>
          <option value="plan_costmap_ctx_used_rate" {"selected" if sort_value == "plan_costmap_ctx_used_rate" else ""}>plan_costmap_ctx_used_rate</option>
          <option value="plan_score" {"selected" if sort_value == "plan_score" else ""}>plan_score</option>
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
      <a href="{base_url}/api/run_packages/export.csv?scenario={scenario_value}&run_id={run_id_value}&has_gt={has_gt_value}&has_pov={has_pov_value}&has_pov_context={has_pov_context_value}&has_plan={has_plan_value}&plan_fallback_used={plan_fallback_used_value}&plan_risk_level={plan_risk_level_value}&min_quality={min_quality_value}&min_pov_decisions={min_pov_decisions_value}&min_pov_context_token_approx={min_pov_context_token_approx_value}&min_plan_score={min_plan_score_value}&max_confirm_timeouts={max_confirm_timeouts_value}&max_critical_misses={max_critical_misses_value}&max_risk_latency_p90={max_risk_latency_p90_value}&max_risk_latency_max={max_risk_latency_max_value}&max_ocr_cer={max_ocr_cer_value}&min_ocr_exact_match_rate={min_ocr_exact_match_rate_value}&min_ocr_coverage={min_ocr_coverage_value}&max_ocr_latency_p90={max_ocr_latency_p90_value}&min_depth_delta1={min_depth_delta1_value}&max_depth_absrel={max_depth_absrel_value}&min_depth_coverage={min_depth_coverage_value}&max_depth_latency_p90={max_depth_latency_p90_value}&min_costmap_coverage={min_costmap_coverage_value}&max_costmap_latency_p90={max_costmap_latency_p90_value}&max_costmap_dynamic_filter_rate_mean={max_costmap_dynamic_filter_rate_mean_value}&min_costmap_fused_coverage={min_costmap_fused_coverage_value}&max_costmap_fused_latency_p90={max_costmap_fused_latency_p90_value}&min_costmap_fused_iou_p90={min_costmap_fused_iou_p90_value}&max_costmap_fused_flicker_rate_mean={max_costmap_fused_flicker_rate_mean_value}&max_costmap_fused_shift_gate_reject_rate={max_costmap_fused_shift_gate_reject_rate_value}&min_costmap_fused_shift_used_rate={min_costmap_fused_shift_used_rate_value}&max_frame_user_e2e_p90={max_frame_user_e2e_p90_value}&max_frame_user_e2e_max={max_frame_user_e2e_max_value}&max_frame_user_e2e_tts_p90={max_frame_user_e2e_tts_p90_value}&max_frame_user_e2e_ar_p90={max_frame_user_e2e_ar_p90_value}&min_ack_kind_diversity={min_ack_kind_diversity_value}&max_models_missing_required={max_models_missing_required_value}&min_seg_f1_50={min_seg_f1_50_value}&min_seg_coverage={min_seg_coverage_value}&min_seg_track_coverage={min_seg_track_coverage_value}&min_seg_tracks_total={min_seg_tracks_total_value}&max_seg_id_switches={max_seg_id_switches_value}&min_seg_mask_f1_50={min_seg_mask_f1_50_value}&min_seg_mask_coverage={min_seg_mask_coverage_value}&max_seg_latency_p90={max_seg_latency_p90_value}&max_seg_ctx_chars={max_seg_ctx_chars_value}&max_seg_ctx_trunc_dropped={max_seg_ctx_trunc_dropped_value}&max_plan_ctx_trunc_rate={max_plan_ctx_trunc_rate_value}&min_plan_ctx_chars_p90={min_plan_ctx_chars_p90_value}&min_seg_prompt_text_chars={min_seg_prompt_text_chars_value}&max_seg_prompt_trunc_rate={max_seg_prompt_trunc_rate_value}&max_seg_prompt_trunc_dropped={max_seg_prompt_trunc_dropped_value}&max_plan_guardrails={max_plan_guardrails_value}&max_plan_latency_p90={max_plan_latency_p90_value}&max_plan_overcautious_rate={max_plan_overcautious_rate_value}&max_plan_guardrail_override_rate={max_plan_guardrail_override_rate_value}&require_plan_costmap_ctx_used={require_plan_costmap_ctx_used_value}&sort={sort_value}&order={order_value}&limit={limit_value}">Export CSV</a>
      <a href="{base_url}/api/run_packages/export.json?scenario={scenario_value}&run_id={run_id_value}&has_gt={has_gt_value}&has_pov={has_pov_value}&has_pov_context={has_pov_context_value}&has_plan={has_plan_value}&plan_fallback_used={plan_fallback_used_value}&plan_risk_level={plan_risk_level_value}&min_quality={min_quality_value}&min_pov_decisions={min_pov_decisions_value}&min_pov_context_token_approx={min_pov_context_token_approx_value}&min_plan_score={min_plan_score_value}&max_confirm_timeouts={max_confirm_timeouts_value}&max_critical_misses={max_critical_misses_value}&max_risk_latency_p90={max_risk_latency_p90_value}&max_risk_latency_max={max_risk_latency_max_value}&max_ocr_cer={max_ocr_cer_value}&min_ocr_exact_match_rate={min_ocr_exact_match_rate_value}&min_ocr_coverage={min_ocr_coverage_value}&max_ocr_latency_p90={max_ocr_latency_p90_value}&min_depth_delta1={min_depth_delta1_value}&max_depth_absrel={max_depth_absrel_value}&min_depth_coverage={min_depth_coverage_value}&max_depth_latency_p90={max_depth_latency_p90_value}&min_costmap_coverage={min_costmap_coverage_value}&max_costmap_latency_p90={max_costmap_latency_p90_value}&max_costmap_dynamic_filter_rate_mean={max_costmap_dynamic_filter_rate_mean_value}&min_costmap_fused_coverage={min_costmap_fused_coverage_value}&max_costmap_fused_latency_p90={max_costmap_fused_latency_p90_value}&min_costmap_fused_iou_p90={min_costmap_fused_iou_p90_value}&max_costmap_fused_flicker_rate_mean={max_costmap_fused_flicker_rate_mean_value}&max_costmap_fused_shift_gate_reject_rate={max_costmap_fused_shift_gate_reject_rate_value}&min_costmap_fused_shift_used_rate={min_costmap_fused_shift_used_rate_value}&max_frame_user_e2e_p90={max_frame_user_e2e_p90_value}&max_frame_user_e2e_max={max_frame_user_e2e_max_value}&max_frame_user_e2e_tts_p90={max_frame_user_e2e_tts_p90_value}&max_frame_user_e2e_ar_p90={max_frame_user_e2e_ar_p90_value}&min_ack_kind_diversity={min_ack_kind_diversity_value}&max_models_missing_required={max_models_missing_required_value}&min_seg_f1_50={min_seg_f1_50_value}&min_seg_coverage={min_seg_coverage_value}&min_seg_track_coverage={min_seg_track_coverage_value}&min_seg_tracks_total={min_seg_tracks_total_value}&max_seg_id_switches={max_seg_id_switches_value}&min_seg_mask_f1_50={min_seg_mask_f1_50_value}&min_seg_mask_coverage={min_seg_mask_coverage_value}&max_seg_latency_p90={max_seg_latency_p90_value}&max_seg_ctx_chars={max_seg_ctx_chars_value}&max_seg_ctx_trunc_dropped={max_seg_ctx_trunc_dropped_value}&max_plan_ctx_trunc_rate={max_plan_ctx_trunc_rate_value}&min_plan_ctx_chars_p90={min_plan_ctx_chars_p90_value}&min_seg_prompt_text_chars={min_seg_prompt_text_chars_value}&max_seg_prompt_trunc_rate={max_seg_prompt_trunc_rate_value}&max_seg_prompt_trunc_dropped={max_seg_prompt_trunc_dropped_value}&max_plan_guardrails={max_plan_guardrails_value}&max_plan_latency_p90={max_plan_latency_p90_value}&max_plan_overcautious_rate={max_plan_overcautious_rate_value}&max_plan_guardrail_override_rate={max_plan_guardrail_override_rate_value}&require_plan_costmap_ctx_used={require_plan_costmap_ctx_used_value}&sort={sort_value}&order={order_value}&limit={limit_value}">Export JSON</a>
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
          <th>ConfirmTimeouts</th>
          <th>Critical FN</th>
          <th>MaxDelay(fr)</th>
          <th>Risk p90(ms)</th>
          <th>OCR CER</th>
          <th>OCR Exact</th>
          <th>OCR Coverage</th>
          <th>OCR p90(ms)</th>
          <th>User E2E p90(ms)</th>
          <th>User E2E max(ms)</th>
          <th>User E2E tts p90(ms)</th>
          <th>User E2E tts max(ms)</th>
          <th>User E2E ar p90(ms)</th>
          <th>User E2E ar max(ms)</th>
          <th>ACK Kind Diversity</th>
          <th>ACK Coverage</th>
          <th>Models Missing</th>
          <th>Models Enabled</th>
          <th>Seg F1@0.5</th>
          <th>Seg Coverage</th>
          <th>Seg Track Coverage</th>
          <th>Seg Tracks Total</th>
          <th>Seg ID Switches</th>
          <th>Seg Mask F1@0.5</th>
          <th>Seg Mask Coverage</th>
          <th>Seg Mask mIoU</th>
          <th>Seg p90(ms)</th>
          <th>Depth AbsRel</th>
          <th>Depth RMSE</th>
          <th>Depth Delta1</th>
          <th>Depth Coverage</th>
          <th>Depth p90(ms)</th>
          <th>Costmap Coverage</th>
          <th>Costmap p90(ms)</th>
          <th>Costmap DensityMean</th>
          <th>Costmap DynamicFilterMean</th>
          <th>Costmap Fused Coverage</th>
          <th>Costmap Fused p90(ms)</th>
          <th>Costmap Fused IoU p90</th>
          <th>Costmap Fused Flicker Mean</th>
          <th>Costmap Fused ShiftUsed Rate</th>
          <th>Costmap Fused ShiftReject Rate</th>
          <th>Costmap Fused ShiftReject TopReason</th>
          <th>SLAM Tracking</th>
          <th>SLAM Lost</th>
          <th>SLAM Relocalized</th>
          <th>SLAM p90(ms)</th>
          <th>SLAM Align p90(ms)</th>
          <th>SLAM Align Mode</th>
          <th>SLAM ATE RMSE(m)</th>
          <th>SLAM RPE RMSE(m)</th>
          <th>SegCtx Chars</th>
          <th>SegCtx Segments</th>
          <th>SegCtx DropSeg</th>
          <th>Seg Prompt</th>
          <th>Seg Prompt Chars</th>
          <th>Seg Prompt Chars Out</th>
          <th>Seg Prompt Targets Out</th>
          <th>Seg Prompt Dropped</th>
          <th>Seg Prompt TruncRate</th>
          <th>POV</th>
          <th>POV Decisions</th>
          <th>POV Token~</th>
          <th>POV DPM</th>
          <th>POV Ctx Token~</th>
          <th>POV Ctx Chars</th>
          <th>Plan</th>
          <th>Plan Risk</th>
          <th>Plan Actions</th>
          <th>Plan Guardrails</th>
          <th>Plan Stop</th>
          <th>Plan Confirm</th>
          <th>Plan Score</th>
          <th>Plan Fallback</th>
          <th>Plan JSON</th>
          <th>Plan Prompt</th>
          <th>Plan p90(ms)</th>
          <th>Confirm Req</th>
          <th>Overcautious</th>
          <th>Guardrail Override</th>
          <th>Plan Costmap Ctx Coverage</th>
          <th>Plan Costmap Ctx Used</th>
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
