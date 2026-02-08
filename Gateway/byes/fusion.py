from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from byes.config import GatewayConfig
from byes.crosscheck import CrossCheckActionPatch, CrossCheckEngine
from byes.hazard_memory import HazardMemory
from byes.schema import (
    ActionPlan,
    ActionStep,
    ActionType,
    CoordFrame,
    EventEnvelope,
    EventType,
    RiskLevel,
    ToolResult,
    ToolStatus,
)
from byes.tools.base import FrameInput, ToolLane
from byes.world_state import WorldState


@dataclass
class FusionOutput:
    stage1_events: list[EventEnvelope] = field(default_factory=list)
    stage2_events: list[EventEnvelope] = field(default_factory=list)
    diagnostics: list[dict[str, object]] = field(default_factory=list)

    @property
    def events(self) -> list[EventEnvelope]:
        return [*self.stage1_events, *self.stage2_events]


class FusionEngine:
    def __init__(
        self,
        config: GatewayConfig,
        metrics: object | None = None,
        world_state: WorldState | None = None,
    ) -> None:
        self._config = config
        self._metrics = metrics
        self._crosscheck = CrossCheckEngine(config)
        self._hazard_memory = HazardMemory(config, metrics=metrics)
        self._world_state = world_state
        self._critical_latch_ms = max(1, int(config.critical_latch_ms))
        self._critical_near_m = max(0.0, float(config.critical_near_m))
        self._critical_crosscheck_kinds = {
            item.strip().lower()
            for item in str(config.critical_from_crosscheck_kinds_csv).split(",")
            if item.strip()
        }

    def reset_runtime(self) -> None:
        self._crosscheck.reset_runtime()
        self._hazard_memory.reset_runtime()

    def fuse_lane(
        self,
        frame: FrameInput,
        lane: ToolLane,
        results: list[ToolResult],
        trace_id: str,
        span_id: str,
        health_status: str = "NORMAL",
    ) -> FusionOutput:
        ok_results = [result for result in results if result.status == ToolStatus.OK]
        normalized_health = str(health_status).strip().upper()
        planner_hints = self._extract_planner_hints(frame.meta)
        session_id = self._session_id_from_meta(frame.meta)
        if not ok_results:
            if lane == ToolLane.FAST and planner_hints and normalized_health != "SAFE_MODE":
                stage1 = self._tag_stage(self._planner_hint_events(frame, trace_id, span_id, planner_hints), "stage1")
                self._update_world_state(
                    frame=frame,
                    session_id=session_id,
                    results=ok_results,
                    diagnostics=[],
                    emitted_events=stage1,
                )
                return FusionOutput(stage1_events=stage1)
            if lane == ToolLane.FAST and normalized_health in {"DEGRADED", "SAFE_MODE"}:
                stage1 = self._tag_stage(
                    [self._conservative_stage1_action_plan(frame, trace_id, span_id, normalized_health)],
                    "stage1",
                )
                self._update_world_state(
                    frame=frame,
                    session_id=session_id,
                    results=ok_results,
                    diagnostics=[],
                    emitted_events=stage1,
                )
                return FusionOutput(stage1_events=stage1)
            self._update_world_state(
                frame=frame,
                session_id=session_id,
                results=ok_results,
                diagnostics=[],
                emitted_events=[],
            )
            return FusionOutput()

        if lane == ToolLane.FAST:
            risk = self._pick_risk(ok_results)
            if risk is None:
                if planner_hints and normalized_health != "SAFE_MODE":
                    stage1 = self._tag_stage(self._planner_hint_events(frame, trace_id, span_id, planner_hints), "stage1")
                    self._update_world_state(
                        frame=frame,
                        session_id=session_id,
                        results=ok_results,
                        diagnostics=[],
                        emitted_events=stage1,
                    )
                    return FusionOutput(stage1_events=stage1)
                if normalized_health in {"DEGRADED", "SAFE_MODE"}:
                    stage1 = self._tag_stage(
                        [self._conservative_stage1_action_plan(frame, trace_id, span_id, normalized_health)],
                        "stage1",
                    )
                    self._update_world_state(
                        frame=frame,
                        session_id=session_id,
                        results=ok_results,
                        diagnostics=[],
                        emitted_events=stage1,
                    )
                    return FusionOutput(stage1_events=stage1)
                self._update_world_state(
                    frame=frame,
                    session_id=session_id,
                    results=ok_results,
                    diagnostics=[],
                    emitted_events=[],
                )
                return FusionOutput()
            event = EventEnvelope(
                type=EventType.RISK,
                traceId=trace_id,
                spanId=span_id,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                ttlMs=frame.ttl_ms,
                coordFrame=risk.coordFrame,
                confidence=risk.confidence,
                priority=self._config.risk_priority,
                source=f"{risk.toolName}@{risk.toolVersion}",
                riskLevel=self._normalize_risk_level(risk.payload.get("riskLevel")),
                criticalReason=(
                    str(risk.payload.get("criticalReason")).strip()
                    if str(risk.payload.get("criticalReason", "")).strip()
                    else None
                ),
                payload={
                    "riskText": risk.payload.get("riskText", "Obstacle ahead"),
                    "distanceM": risk.payload.get("distanceM"),
                    "azimuthDeg": risk.payload.get("azimuthDeg"),
                    "summary": risk.payload.get("summary", risk.payload.get("riskText", "Obstacle ahead")),
                    "riskLevel": self._normalize_risk_level(risk.payload.get("riskLevel")).value,
                    "criticalReason": (
                        str(risk.payload.get("criticalReason")).strip()
                        if str(risk.payload.get("criticalReason", "")).strip()
                        else None
                    ),
                    "reason": "risk_lane",
                    "actionCategory": "risk_lane",
                    "activeConfirm": bool(risk.payload.get("activeConfirm", False)),
                    "crosscheckKind": risk.payload.get("crosscheckKind"),
                },
            )
            risk_events = self._upgrade_fast_risk_events_from_latch(frame, session_id, [event])
            if self._has_critical_risk(risk_events):
                events = self._tag_stage(risk_events, "stage1")
            else:
                events = self._tag_stage(self._apply_hazard_memory(frame, risk_events), "stage1")
            if planner_hints and normalized_health != "SAFE_MODE":
                events.extend(self._tag_stage(self._planner_hint_events(frame, trace_id, span_id, planner_hints), "stage1"))
            self._update_world_state(
                frame=frame,
                session_id=session_id,
                results=ok_results,
                diagnostics=[],
                emitted_events=events,
            )
            return FusionOutput(stage1_events=events)

        events: list[EventEnvelope] = []
        diagnostics: list[dict[str, object]] = []
        perception_payload = self._build_perception_payload(ok_results)
        perception_event: EventEnvelope | None = None
        if perception_payload is not None:
            perception_event = EventEnvelope(
                type=EventType.PERCEPTION,
                traceId=trace_id,
                spanId=span_id,
                seq=frame.seq,
                tsCaptureMs=frame.ts_capture_ms,
                ttlMs=frame.ttl_ms,
                coordFrame=CoordFrame.WORLD,
                confidence=perception_payload["confidence"],
                priority=self._config.perception_priority,
                source=perception_payload["source"],
                payload=perception_payload["payload"],
            )
            events.append(perception_event)

        depth = self._pick_depth(ok_results)
        det = self._pick_det(ok_results)
        vlm = self._pick_vlm(ok_results)

        crosscheck = self._crosscheck.evaluate(
            det_result=det,
            depth_result=depth,
            frame_meta=frame.meta if isinstance(frame.meta, dict) else None,
            health_status=health_status,
            session_id=str(frame.meta.get("sessionId", "default")),
            now_ms=frame.ts_capture_ms,
        )
        for item in crosscheck.diagnostics:
            diagnostics.append(
                {
                    "kind": item.kind,
                    "activeConfirm": item.active_confirm,
                    "patched": False,
                    "details": dict(item.details),
                }
            )
        crosscheck_risk: EventEnvelope | None = None
        if crosscheck.risks:
            crosscheck_risk = self._risk_event_from_payload(
                frame=frame,
                trace_id=trace_id,
                span_id=span_id,
                payload=crosscheck.risks[0],
            )
            events.append(crosscheck_risk)

        risk_from_depth = self._risk_from_depth(depth, frame, trace_id, span_id)
        risk_semantic = self._risk_from_det(det, frame, trace_id, span_id)
        if crosscheck_risk is None and risk_from_depth is not None:
            events.append(risk_from_depth)
        if crosscheck_risk is None and risk_semantic is not None:
            events.append(risk_semantic)

        risk_for_plan = crosscheck_risk or risk_from_depth or risk_semantic
        action_plan = self._action_plan_from_semantics(
            frame=frame,
            trace_id=trace_id,
            span_id=span_id,
            perception=perception_event,
            risk=risk_for_plan,
            depth=depth,
        )
        vlm_action_plan = self._action_plan_from_vlm(
            frame=frame,
            trace_id=trace_id,
            span_id=span_id,
            vlm=vlm,
        )
        if vlm_action_plan is not None:
            events.append(vlm_action_plan)
        if action_plan is not None and crosscheck.action_patch is not None and health_status.upper() != "SAFE_MODE":
            self._apply_crosscheck_patch(action_plan, crosscheck.action_patch)
            for item in diagnostics:
                if item.get("kind") == crosscheck.action_patch.kind:
                    item["patched"] = True
                    break
        if action_plan is not None:
            events.append(action_plan)
        events = self._tag_stage(self._apply_hazard_memory(frame, events), "stage2")
        self._update_world_state(
            frame=frame,
            session_id=session_id,
            results=ok_results,
            diagnostics=diagnostics,
            emitted_events=events,
        )
        return FusionOutput(stage2_events=events, diagnostics=diagnostics)

    @staticmethod
    def to_legacy_event(event: EventEnvelope) -> dict[str, object | None]:
        payload = event.payload
        if event.type == EventType.RISK:
            return {
                "type": "risk",
                "seq": event.seq,
                "timestampMs": event.tsEmitMs,
                "coordFrame": event.coordFrame.value,
                "confidence": event.confidence,
                "ttlMs": event.ttlMs,
                "source": event.source,
                "riskLevel": (
                    event.riskLevel.value
                    if event.riskLevel is not None
                    else str(payload.get("riskLevel", RiskLevel.WARN.value))
                ),
                "criticalReason": (
                    event.criticalReason
                    if event.criticalReason is not None
                    else payload.get("criticalReason")
                ),
                "stage": payload.get("stage"),
                "riskText": payload.get("riskText"),
                "summary": payload.get("summary"),
                "distanceM": payload.get("distanceM"),
                "azimuthDeg": payload.get("azimuthDeg"),
                "reason": payload.get("reason"),
                "actionCategory": payload.get("actionCategory"),
                "activeConfirm": payload.get("activeConfirm"),
                "crosscheckKind": payload.get("crosscheckKind"),
                "hazardId": payload.get("hazardId"),
                "hazardKind": payload.get("hazardKind"),
                "hazardState": payload.get("hazardState"),
            }

        if event.type == EventType.PERCEPTION:
            return {
                "type": "perception",
                "seq": event.seq,
                "timestampMs": event.tsEmitMs,
                "coordFrame": event.coordFrame.value,
                "confidence": event.confidence,
                "ttlMs": event.ttlMs,
                "source": event.source,
                "stage": payload.get("stage"),
                "summary": payload.get("summary"),
                "riskText": None,
                "distanceM": None,
                "azimuthDeg": None,
            }

        if event.type == EventType.ACTION_PLAN:
            return {
                "type": "action_plan",
                "seq": event.seq,
                "timestampMs": event.tsEmitMs,
                "coordFrame": event.coordFrame.value,
                "confidence": event.confidence,
                "ttlMs": event.ttlMs,
                "source": event.source,
                "stage": payload.get("stage"),
                "summary": payload.get("summary"),
                "actionPlan": payload.get("plan"),
                "speech": payload.get("speech"),
                "hud": payload.get("hud"),
                "reason": payload.get("reason"),
                "actionCategory": payload.get("actionCategory", payload.get("reason")),
                "activeConfirm": payload.get("activeConfirm"),
                "crosscheckKind": payload.get("crosscheckKind"),
                "riskText": None,
                "distanceM": None,
                "azimuthDeg": None,
            }

        if event.type == EventType.DIALOG:
            return {
                "type": "dialog",
                "seq": event.seq,
                "timestampMs": event.tsEmitMs,
                "coordFrame": event.coordFrame.value,
                "confidence": event.confidence,
                "ttlMs": event.ttlMs,
                "source": event.source,
                "stage": payload.get("stage"),
                "summary": payload.get("summary", payload.get("text", "")),
                "text": payload.get("text"),
                "riskText": None,
                "distanceM": None,
                "azimuthDeg": None,
            }

        return {
            "type": "health",
            "seq": event.seq,
            "timestampMs": event.tsEmitMs,
            "coordFrame": event.coordFrame.value,
            "confidence": event.confidence,
            "ttlMs": event.ttlMs,
            "source": event.source,
            "stage": payload.get("stage"),
            "summary": payload.get("summary", payload.get("status", "health")),
            "healthStatus": (
                event.healthStatus.value
                if event.healthStatus is not None
                else payload.get("healthStatus")
            ),
            "healthReason": (
                event.healthReason
                if event.healthReason is not None
                else payload.get("healthReason", payload.get("reason"))
            ),
            "riskText": None,
            "distanceM": None,
            "azimuthDeg": None,
        }

    @staticmethod
    def _pick_risk(results: list[ToolResult]) -> ToolResult | None:
        candidates = [item for item in results if "riskText" in item.payload]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.confidence)

    @staticmethod
    def _pick_ocr(results: list[ToolResult]) -> ToolResult | None:
        candidates = [item for item in results if "text" in item.payload]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.confidence)

    def _pick_det(self, results: list[ToolResult]) -> ToolResult | None:
        candidates = [item for item in results if isinstance(item.payload.get("detections"), list)]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.confidence)

    def _pick_depth(self, results: list[ToolResult]) -> ToolResult | None:
        candidates = [item for item in results if isinstance(item.payload.get("hazards"), list)]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.confidence)

    def _pick_vlm(self, results: list[ToolResult]) -> ToolResult | None:
        candidates = [
            item
            for item in results
            if item.toolName == "real_vlm"
            or isinstance(item.payload.get("actionPlan"), dict)
            or isinstance(item.payload.get("answerText"), str)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.confidence)

    def _build_perception_payload(self, results: list[ToolResult]) -> dict[str, object] | None:
        ocr = self._pick_ocr(results)
        det = self._pick_det(results)
        depth = self._pick_depth(results)
        if ocr is None and det is None and depth is None:
            return None

        if ocr is not None and det is not None:
            confidence = max(0.0, min(1.0, (ocr.confidence * 0.5) + (det.confidence * 0.5)))
            summary = (
                str(ocr.payload.get("text", ""))
                or str(det.payload.get("summary", "Perception detected"))
                or (str(depth.payload.get("summary", "")) if depth is not None else "Perception detected")
            )
            return {
                "confidence": confidence,
                "source": f"{ocr.toolName}@{ocr.toolVersion}",
                "payload": {
                    "summary": summary,
                    "reason": "multi_source_normalized",
                    "detections": det.payload.get("detections", []),
                    "hazards": depth.payload.get("hazards", []) if depth is not None else [],
                    "riskText": None,
                    "distanceM": None,
                    "azimuthDeg": None,
                },
            }

        if ocr is not None:
            return {
                "confidence": ocr.confidence,
                "source": f"{ocr.toolName}@{ocr.toolVersion}",
                "payload": {
                    "summary": ocr.payload.get("text", "Perception detected"),
                    "reason": "single_source_ocr",
                    "hazards": depth.payload.get("hazards", []) if depth is not None else [],
                    "riskText": None,
                    "distanceM": None,
                    "azimuthDeg": None,
                },
            }

        if det is not None:
            return {
                "confidence": det.confidence,
                "source": f"{det.toolName}@{det.toolVersion}",
                "payload": {
                    "summary": det.payload.get("summary", "Perception detected"),
                    "reason": "single_source_det",
                    "detections": det.payload.get("detections", []),
                    "hazards": depth.payload.get("hazards", []) if depth is not None else [],
                    "riskText": None,
                    "distanceM": None,
                    "azimuthDeg": None,
                },
            }

        assert depth is not None
        return {
            "confidence": depth.confidence,
            "source": f"{depth.toolName}@{depth.toolVersion}",
            "payload": {
                "summary": depth.payload.get("summary", "Depth updated"),
                "reason": "single_source_depth",
                "hazards": depth.payload.get("hazards", []),
                "riskText": None,
                "distanceM": None,
                "azimuthDeg": None,
            },
        }

    def _risk_from_det(
        self,
        det: ToolResult | None,
        frame: FrameInput,
        trace_id: str,
        span_id: str,
    ) -> EventEnvelope | None:
        if det is None:
            return None
        detections = det.payload.get("detections")
        if not isinstance(detections, list) or not detections:
            return None

        top = None
        for item in detections:
            if not isinstance(item, dict):
                continue
            if top is None:
                top = item
                continue
            if float(item.get("confidence", 0.0)) > float(top.get("confidence", 0.0)):
                top = item
        if top is None:
            return None

        cls = str(top.get("class", "object")).lower()
        conf = max(0.0, min(1.0, float(top.get("confidence", 0.0))))
        risky_classes = {"person", "car", "truck", "bike", "stairs", "stair", "wall", "obstacle"}
        if conf < 0.6 or cls not in risky_classes:
            return None

        return EventEnvelope(
            type=EventType.RISK,
            traceId=trace_id,
            spanId=span_id,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            ttlMs=frame.ttl_ms,
            coordFrame=CoordFrame.WORLD,
            confidence=conf,
            priority=self._config.risk_priority,
            source=f"{det.toolName}@{det.toolVersion}",
            riskLevel=RiskLevel.WARN,
            payload={
                "riskText": f"Potential obstacle: {cls}",
                "distanceM": None,
                "azimuthDeg": self._compute_azimuth_from_meta(frame, top),
                "summary": f"{cls} detected in front",
                "riskLevel": RiskLevel.WARN.value,
                "reason": "det_semantic_risk",
            },
        )

    def _risk_from_depth(
        self,
        depth: ToolResult | None,
        frame: FrameInput,
        trace_id: str,
        span_id: str,
    ) -> EventEnvelope | None:
        if depth is None:
            return None
        hazards = depth.payload.get("hazards")
        if not isinstance(hazards, list) or not hazards:
            return None

        chosen: dict[str, object] | None = None
        for item in hazards:
            if not isinstance(item, dict):
                continue
            try:
                distance_m = float(item.get("distanceM"))
                azimuth_deg = float(item.get("azimuthDeg"))
                confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
            except (TypeError, ValueError):
                continue
            if distance_m >= float(self._config.real_depth_hazard_distance_threshold_m):
                continue
            if abs(azimuth_deg) > float(self._config.real_depth_hazard_azimuth_threshold_deg):
                continue
            if chosen is None or distance_m < float(chosen.get("distanceM", 9999.0)):
                chosen = {
                    "distanceM": distance_m,
                    "azimuthDeg": azimuth_deg,
                    "confidence": confidence,
                    "kind": str(item.get("kind", "obstacle")),
                }

        if chosen is None:
            return None

        kind = str(chosen.get("kind", "obstacle"))
        distance_m = float(chosen.get("distanceM", 0.0))
        azimuth_deg = float(chosen.get("azimuthDeg", 0.0))
        confidence = float(chosen.get("confidence", 0.0))
        return EventEnvelope(
            type=EventType.RISK,
            traceId=trace_id,
            spanId=span_id,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            ttlMs=frame.ttl_ms,
            coordFrame=CoordFrame.WORLD,
            confidence=confidence,
            priority=self._config.risk_priority,
            source=f"{depth.toolName}@{depth.toolVersion}",
            riskLevel=RiskLevel.WARN,
            payload={
                "riskText": f"Depth hazard ahead: {kind}",
                "distanceM": distance_m,
                "azimuthDeg": azimuth_deg,
                "summary": f"{kind} at {distance_m:.2f}m ahead",
                "riskLevel": RiskLevel.WARN.value,
                "reason": "depth_hazard_risk",
            },
        )

    def _action_plan_from_semantics(
        self,
        frame: FrameInput,
        trace_id: str,
        span_id: str,
        perception: EventEnvelope | None,
        risk: EventEnvelope | None,
        depth: ToolResult | None,
    ) -> EventEnvelope | None:
        if perception is None and risk is None:
            return None

        if risk is not None:
            steps = [
                ActionStep(action=ActionType.STOP, text="Stop immediately."),
                ActionStep(action=ActionType.SCAN, text="Scan surroundings before moving."),
            ]
            mode = "risk"
            overall_conf = risk.confidence
            speech = "Potential risk detected. Stop and scan surroundings."
            hud = "Risk detected: stop and scan"
            summary = str(risk.payload.get("summary", "Risk detected"))
            source = risk.source
        else:
            assert perception is not None
            depth_available = (
                depth is not None and isinstance(depth.payload.get("hazards"), list)
            )
            if depth_available:
                steps = [
                    ActionStep(action=ActionType.MOVE, text="Proceed carefully."),
                    ActionStep(action=ActionType.CONFIRM, text="Confirm path remains clear."),
                ]
                mode = "assist"
                speech_prefix = "Perception updated."
                hud_prefix = ""
            else:
                # Depth lane missing/timeout: bias action plan to conservative scan.
                steps = [
                    ActionStep(action=ActionType.SCAN, text="Scan surroundings for safety."),
                    ActionStep(action=ActionType.CONFIRM, text="Confirm path before moving."),
                ]
                mode = "degraded_assist"
                speech_prefix = "Depth unavailable."
                hud_prefix = "Depth unavailable. "
            overall_conf = perception.confidence
            summary = str(perception.payload.get("summary", "Perception updated"))
            speech = f"{speech_prefix} {summary}".strip()
            hud = f"{hud_prefix}{summary}".strip()
            source = perception.source

        plan = ActionPlan(
            traceId=trace_id,
            expiresMs=frame.ts_capture_ms + frame.ttl_ms,
            mode=mode,
            overallConfidence=overall_conf,
            steps=steps,
            fallback=ActionType.SCAN.value,
        )

        return EventEnvelope(
            type=EventType.ACTION_PLAN,
            traceId=trace_id,
            spanId=span_id,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            ttlMs=frame.ttl_ms,
            coordFrame=CoordFrame.WORLD,
            confidence=overall_conf,
            priority=self._config.navigation_priority,
            source=source,
            payload={
                "summary": summary,
                "speech": speech,
                "hud": hud,
                "plan": plan.model_dump(mode="json"),
                "reason": "semantic_policy",
                "actionCategory": "semantic",
            },
        )

    def _action_plan_from_vlm(
        self,
        *,
        frame: FrameInput,
        trace_id: str,
        span_id: str,
        vlm: ToolResult | None,
    ) -> EventEnvelope | None:
        if vlm is None:
            return None
        payload = vlm.payload if isinstance(vlm.payload, dict) else {}
        raw_plan = payload.get("actionPlan")
        if not isinstance(raw_plan, dict):
            raw_plan = {}
        answer_text = str(payload.get("answerText", "")).strip()
        speech = str(raw_plan.get("speech") or answer_text or "VLM guidance available").strip()
        hud_raw = raw_plan.get("hud")
        if isinstance(hud_raw, list):
            hud_text = " | ".join(str(item).strip() for item in hud_raw if str(item).strip())
        else:
            hud_text = str(hud_raw or speech).strip()
        summary = str(raw_plan.get("summary") or answer_text or speech).strip()
        confidence = vlm.confidence
        try:
            confidence = max(0.0, min(1.0, float(raw_plan.get("confidence", confidence))))
        except (TypeError, ValueError):
            confidence = max(0.0, min(1.0, confidence))

        steps_payload = raw_plan.get("steps")
        steps: list[ActionStep] = []
        if isinstance(steps_payload, list):
            for step in steps_payload:
                if not isinstance(step, dict):
                    continue
                action_name = str(step.get("action", ActionType.CONFIRM.value)).strip().lower()
                try:
                    action = ActionType(action_name)
                except ValueError:
                    action = ActionType.CONFIRM
                steps.append(
                    ActionStep(
                        action=action,
                        text=str(step.get("text", "")).strip() or None,
                        distanceM=_optional_float(step.get("distanceM")),
                        azimuthDeg=_optional_float(step.get("azimuthDeg")),
                        params=step.get("params") if isinstance(step.get("params"), dict) else {},
                    )
                )
        if not steps:
            steps = [ActionStep(action=ActionType.CONFIRM, text=speech)]

        fallback = str(raw_plan.get("fallback", ActionType.CONFIRM.value)).strip().lower()
        if fallback not in {item.value for item in ActionType}:
            fallback = ActionType.CONFIRM.value

        mode = str(raw_plan.get("mode", "ask")).strip() or "ask"
        plan = ActionPlan(
            traceId=trace_id,
            expiresMs=frame.ts_capture_ms + frame.ttl_ms,
            mode=mode,
            overallConfidence=confidence,
            steps=steps,
            fallback=fallback,
        )

        return EventEnvelope(
            type=EventType.ACTION_PLAN,
            traceId=trace_id,
            spanId=span_id,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            ttlMs=frame.ttl_ms,
            coordFrame=CoordFrame.WORLD,
            confidence=confidence,
            priority=self._config.navigation_priority,
            source=f"{vlm.toolName}@{vlm.toolVersion}",
            payload={
                "summary": summary,
                "speech": speech,
                "hud": hud_text,
                "answerText": answer_text,
                "plan": plan.model_dump(mode="json"),
                "tags": raw_plan.get("tags") if isinstance(raw_plan.get("tags"), list) else [],
                "reason": "real_vlm",
                "actionCategory": "ask_qa",
            },
        )

    def _compute_azimuth_from_meta(self, frame: FrameInput, det: dict[str, object]) -> float | None:
        frame_meta = frame.meta.get("frameMeta")
        if not isinstance(frame_meta, dict):
            return None
        intrinsics = frame_meta.get("intrinsics")
        if not isinstance(intrinsics, dict):
            return None

        bbox = det.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            return None

        try:
            fx = float(intrinsics.get("fx"))
            cx = float(intrinsics.get("cx"))
        except (TypeError, ValueError):
            return None
        if fx == 0:
            return None

        try:
            x1 = float(bbox[0])
            x2 = float(bbox[2])
            center_x = (x1 + x2) * 0.5
        except (TypeError, ValueError):
            return None

        width_raw = intrinsics.get("width")
        try:
            width = float(width_raw)
        except (TypeError, ValueError):
            width = 0.0

        # Accept either normalized bbox [0,1] or pixel-space bbox.
        if width > 1.0 and -1.5 <= center_x <= 1.5:
            center_x = center_x * width

        azimuth_rad = math.atan((center_x - cx) / fx)
        return math.degrees(azimuth_rad)

    def _risk_event_from_payload(
        self,
        *,
        frame: FrameInput,
        trace_id: str,
        span_id: str,
        payload: dict[str, object],
    ) -> EventEnvelope:
        confidence = payload.get("confidence", 0.85)
        try:
            risk_conf = float(confidence)
        except (TypeError, ValueError):
            risk_conf = 0.85
        return EventEnvelope(
            type=EventType.RISK,
            traceId=trace_id,
            spanId=span_id,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            ttlMs=frame.ttl_ms,
            coordFrame=CoordFrame.WORLD,
            confidence=max(0.0, min(1.0, risk_conf)),
            priority=self._config.risk_priority,
            source="crosscheck@v1.4",
            riskLevel=self._normalize_risk_level(payload.get("riskLevel", payload.get("severity", "warn"))),
            criticalReason=(
                str(payload.get("criticalReason")).strip()
                if str(payload.get("criticalReason", "")).strip()
                else None
            ),
            payload={
                "riskText": payload.get("riskText", "Cross-check hazard"),
                "distanceM": payload.get("distanceM"),
                "azimuthDeg": payload.get("azimuthDeg"),
                "summary": payload.get("summary", payload.get("riskText", "Cross-check hazard")),
                "riskLevel": self._normalize_risk_level(payload.get("riskLevel", payload.get("severity", "warn"))).value,
                "criticalReason": (
                    str(payload.get("criticalReason")).strip()
                    if str(payload.get("criticalReason", "")).strip()
                    else None
                ),
                "reason": "crosscheck",
                "severity": payload.get("severity", "warning"),
                "activeConfirm": bool(payload.get("activeConfirm", True)),
                "crosscheckKind": payload.get("crosscheckKind"),
            },
        )

    def _apply_crosscheck_patch(self, event: EventEnvelope, patch: CrossCheckActionPatch) -> None:
        payload = dict(event.payload)
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            return
        steps = []
        for step in patch.steps:
            if not isinstance(step, dict):
                continue
            steps.append(dict(step))
        if not steps:
            return
        plan["steps"] = steps
        plan["mode"] = "active_confirm"
        plan["fallback"] = ActionType.SCAN.value
        payload["plan"] = plan
        payload["summary"] = patch.summary
        payload["speech"] = patch.speech
        payload["hud"] = patch.hud
        payload["reason"] = "crosscheck_patch"
        payload["actionCategory"] = "crosscheck"
        payload["activeConfirm"] = bool(patch.active_confirm)
        payload["crosscheckKind"] = patch.kind
        event.payload = payload

    def _apply_hazard_memory(self, frame: FrameInput, events: list[EventEnvelope]) -> list[EventEnvelope]:
        if not events:
            return events
        risk_candidates = [item for item in events if item.type == EventType.RISK]
        if not risk_candidates:
            return events
        session_id = "default"
        if isinstance(frame.meta, dict):
            raw_session = frame.meta.get("sessionId")
            if raw_session is not None and str(raw_session).strip():
                session_id = str(raw_session).strip()
        filtered = self._hazard_memory.update_and_filter(
            session_id=session_id,
            risks=risk_candidates,
            now_ms=frame.ts_capture_ms,
        )
        allowed = {item.id for item in filtered}
        ordered: list[EventEnvelope] = []
        for event in events:
            if event.type != EventType.RISK or event.id in allowed:
                ordered.append(event)
        return ordered

    def _conservative_stage1_action_plan(
        self,
        frame: FrameInput,
        trace_id: str,
        span_id: str,
        health_status: str,
    ) -> EventEnvelope:
        summary = "System degraded. Stop and scan before any movement."
        if health_status == "SAFE_MODE":
            summary = "Safe mode active. Stop and wait for risk guidance."
        plan = ActionPlan(
            traceId=trace_id,
            expiresMs=frame.ts_capture_ms + frame.ttl_ms,
            mode="stage1_guard",
            overallConfidence=0.99,
            steps=[
                ActionStep(action=ActionType.STOP, text="Stop immediately."),
                ActionStep(action=ActionType.SCAN, text="Scan surroundings slowly."),
                ActionStep(action=ActionType.CONFIRM, text="Confirm it is safe before moving."),
            ],
            fallback=ActionType.SCAN.value,
        )
        return EventEnvelope(
            type=EventType.ACTION_PLAN,
            traceId=trace_id,
            spanId=span_id,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            ttlMs=frame.ttl_ms,
            coordFrame=CoordFrame.WORLD,
            confidence=0.99,
            priority=self._config.navigation_priority,
            source="stage1_guard@v1.8",
            payload={
                "summary": summary,
                "speech": summary,
                "hud": "Stop and scan",
                "plan": plan.model_dump(mode="json"),
                "reason": "stage1_guard",
                "actionCategory": "stage1_guard",
            },
        )

    def _planner_hint_events(
        self,
        frame: FrameInput,
        trace_id: str,
        span_id: str,
        hints: list[dict[str, Any]],
    ) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        for hint in hints:
            event = self._planner_hint_action_plan(frame, trace_id, span_id, hint)
            if event is not None:
                events.append(event)
        return events

    def _planner_hint_action_plan(
        self,
        frame: FrameInput,
        trace_id: str,
        span_id: str,
        hint: dict[str, Any],
    ) -> EventEnvelope | None:
        if not isinstance(hint, dict):
            return None
        summary = str(hint.get("summary", "")).strip()
        speech = str(hint.get("speech", summary)).strip() or summary
        hud = str(hint.get("hud", speech)).strip() or speech
        if not summary:
            return None
        steps_raw = hint.get("steps")
        steps: list[ActionStep] = []
        if isinstance(steps_raw, list):
            for item in steps_raw:
                if not isinstance(item, dict):
                    continue
                action_raw = str(item.get("action", ActionType.CONFIRM.value)).strip().lower()
                try:
                    action = ActionType(action_raw)
                except ValueError:
                    action = ActionType.CONFIRM
                steps.append(
                    ActionStep(
                        action=action,
                        text=str(item.get("text", "")).strip() or None,
                    )
                )
        if not steps:
            steps = [ActionStep(action=ActionType.CONFIRM, text=speech)]
        fallback = str(hint.get("fallback", ActionType.SCAN.value)).strip().lower()
        if fallback not in {item.value for item in ActionType}:
            fallback = ActionType.SCAN.value
        plan = ActionPlan(
            traceId=trace_id,
            expiresMs=frame.ts_capture_ms + frame.ttl_ms,
            mode=str(hint.get("mode", "planner_hint")),
            overallConfidence=max(0.0, min(1.0, float(hint.get("confidence", 0.8)))),
            steps=steps,
            fallback=fallback,
        )
        reason = str(hint.get("reason", "planner_hint")).strip().lower() or "planner_hint"
        action_category = str(hint.get("actionCategory", reason)).strip().lower() or reason
        return EventEnvelope(
            type=EventType.ACTION_PLAN,
            traceId=trace_id,
            spanId=span_id,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            ttlMs=frame.ttl_ms,
            coordFrame=CoordFrame.WORLD,
            confidence=max(0.0, min(1.0, float(hint.get("confidence", 0.8)))),
            priority=self._config.navigation_priority,
            source="planner_v1@v2.0",
            payload={
                "summary": summary,
                "speech": speech,
                "hud": hud,
                "plan": plan.model_dump(mode="json"),
                "reason": reason,
                "actionCategory": action_category,
            },
        )

    @staticmethod
    def _extract_planner_hints(meta: dict[str, Any]) -> list[dict[str, Any]]:
        raw = meta.get("_plannerActionHints")
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    @staticmethod
    def _session_id_from_meta(meta: dict[str, Any]) -> str:
        session_id = str(meta.get("sessionId", "")).strip()
        return session_id or "default"

    def _is_critical_crosscheck_kind(self, kind: str) -> bool:
        normalized = str(kind or "").strip().lower()
        if not normalized:
            return False
        if normalized in self._critical_crosscheck_kinds:
            return True
        alias_map = {
            "transparent_obstacle": {"vision_without_depth"},
            "dropoff": {"depth_without_vision"},
        }
        for token, aliases in alias_map.items():
            if token in self._critical_crosscheck_kinds and normalized in aliases:
                return True
        return False

    @staticmethod
    def _nearest_depth_distance(results: list[ToolResult]) -> float | None:
        nearest: float | None = None
        for result in results:
            payload = result.payload if isinstance(result.payload, dict) else {}
            hazards = payload.get("hazards")
            if not isinstance(hazards, list):
                continue
            for hazard in hazards:
                if not isinstance(hazard, dict):
                    continue
                try:
                    distance = float(hazard.get("distanceM"))
                except (TypeError, ValueError):
                    continue
                if nearest is None or distance < nearest:
                    nearest = distance
        return nearest

    def _has_persisted_hazard(self, events: list[EventEnvelope]) -> bool:
        for event in events:
            if event.type != EventType.RISK:
                continue
            state = str(event.payload.get("hazardState", "")).strip().lower()
            if state != "persisted":
                continue
            kind = str(event.payload.get("hazardKind", "")).strip().lower()
            if kind in {"dropoff", "transparent"}:
                return True
            distance_m = _optional_float(event.payload.get("distanceM"))
            if distance_m is not None and distance_m <= self._critical_near_m:
                return True
        return False

    def _has_critical_risk(self, events: list[EventEnvelope]) -> bool:
        for event in events:
            if event.type != EventType.RISK:
                continue
            level = self._normalize_risk_level(
                event.riskLevel if event.riskLevel is not None else event.payload.get("riskLevel")
            )
            if level == RiskLevel.CRITICAL:
                return True
        return False

    def _update_world_state(
        self,
        *,
        frame: FrameInput,
        session_id: str,
        results: list[ToolResult],
        diagnostics: list[dict[str, object]],
        emitted_events: list[EventEnvelope],
    ) -> None:
        if self._world_state is None:
            return
        now_ms = _runtime_now_ms()
        crosscheck_kinds: set[str] = set()
        try:
            self._world_state.ingest_tool_results(
                session_id=session_id,
                results=results,
                now_ms=now_ms,
                frame_meta=frame.meta,
            )
        except Exception:  # noqa: BLE001
            pass
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "")).strip()
            if not kind:
                continue
            crosscheck_kinds.add(kind.lower())
            try:
                self._world_state.note_crosscheck_conflict(
                    session_id=session_id,
                    kind=kind,
                    now_ms=now_ms,
                )
            except Exception:  # noqa: BLE001
                pass
        hazards = self._hazard_memory.snapshot(session_id)
        try:
            self._world_state.update_active_hazards(
                session_id=session_id,
                hazards=hazards,
                now_ms=now_ms,
            )
        except Exception:  # noqa: BLE001
            pass

        try:
            self._update_critical_latch_from_evidence(
                frame=frame,
                session_id=session_id,
                results=results,
                emitted_events=emitted_events,
                crosscheck_kinds=crosscheck_kinds,
                now_ms=now_ms,
            )
        except Exception:  # noqa: BLE001
            pass

    def _update_critical_latch_from_evidence(
        self,
        *,
        frame: FrameInput,
        session_id: str,
        results: list[ToolResult],
        emitted_events: list[EventEnvelope],
        crosscheck_kinds: set[str],
        now_ms: int,
    ) -> None:
        if self._world_state is None:
            return
        if any(self._is_critical_crosscheck_kind(kind) for kind in crosscheck_kinds):
            self._world_state.set_critical(now_ms, self._critical_latch_ms, "crosscheck", session_id=session_id)
            return

        near_distance = self._nearest_depth_distance(results)
        if near_distance is not None and near_distance <= self._critical_near_m:
            self._world_state.set_critical(now_ms, self._critical_latch_ms, "depth_near", session_id=session_id)
            return

        if self._has_persisted_hazard(emitted_events):
            self._world_state.set_critical(now_ms, self._critical_latch_ms, "hazard_persist", session_id=session_id)
            return

        if str(frame.meta.get("criticalLatchReason", "")).strip() == "dev_inject":
            self._world_state.set_critical(now_ms, self._critical_latch_ms, "dev_inject", session_id=session_id)

    def _upgrade_fast_risk_events_from_latch(
        self,
        frame: FrameInput,
        session_id: str,
        events: list[EventEnvelope],
    ) -> list[EventEnvelope]:
        if self._world_state is None:
            return events
        now_ms = _runtime_now_ms()
        if not self._world_state.is_critical_active(now_ms, session_id=session_id):
            return events
        reason = self._world_state.get_critical_reason(now_ms, session_id=session_id) or "crosscheck"
        upgraded: list[EventEnvelope] = []
        for event in events:
            if event.type != EventType.RISK:
                upgraded.append(event)
                continue
            current = self._normalize_risk_level(
                event.riskLevel if event.riskLevel is not None else event.payload.get("riskLevel")
            )
            if current != RiskLevel.CRITICAL:
                event.riskLevel = RiskLevel.CRITICAL
                event.criticalReason = reason
                payload = dict(event.payload)
                payload["riskLevel"] = RiskLevel.CRITICAL.value
                payload["criticalReason"] = reason
                event.payload = payload
                self._metric_call("inc_risklevel_upgrade", current.value, RiskLevel.CRITICAL.value, reason)
            else:
                payload = dict(event.payload)
                if "criticalReason" not in payload:
                    payload["criticalReason"] = reason
                    event.payload = payload
                if event.criticalReason is None:
                    event.criticalReason = reason
            upgraded.append(event)
        return upgraded

    @staticmethod
    def _tag_stage(events: list[EventEnvelope], stage: str) -> list[EventEnvelope]:
        tagged: list[EventEnvelope] = []
        for event in events:
            payload = dict(event.payload)
            payload["stage"] = stage
            if event.type == EventType.RISK and "riskLevel" not in payload:
                payload["riskLevel"] = (
                    event.riskLevel.value if event.riskLevel is not None else RiskLevel.WARN.value
                )
            if event.type == EventType.RISK and event.criticalReason is not None and "criticalReason" not in payload:
                payload["criticalReason"] = event.criticalReason
            patched = event.model_copy(deep=True)
            patched.payload = payload
            tagged.append(patched)
        return tagged

    @staticmethod
    def _normalize_risk_level(value: object) -> RiskLevel:
        if isinstance(value, RiskLevel):
            return value
        raw = str(value or "").strip().lower()
        if raw == RiskLevel.INFO.value:
            return RiskLevel.INFO
        if raw == RiskLevel.CRITICAL.value:
            return RiskLevel.CRITICAL
        return RiskLevel.WARN

    def _metric_call(self, method: str, *args: Any) -> None:
        if self._metrics is None:
            return
        fn = getattr(self._metrics, method, None)
        if callable(fn):
            fn(*args)


def _optional_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _runtime_now_ms() -> int:
    return int(time.time() * 1000)
