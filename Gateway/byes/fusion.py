from __future__ import annotations

import math
from dataclasses import dataclass, field

from byes.config import GatewayConfig
from byes.crosscheck import CrossCheckActionPatch, CrossCheckEngine
from byes.hazard_memory import HazardMemory
from byes.schema import ActionPlan, ActionStep, ActionType, CoordFrame, EventEnvelope, EventType, ToolResult, ToolStatus
from byes.tools.base import FrameInput, ToolLane


@dataclass
class FusionOutput:
    events: list[EventEnvelope]
    diagnostics: list[dict[str, object]] = field(default_factory=list)


class FusionEngine:
    def __init__(self, config: GatewayConfig, metrics: object | None = None) -> None:
        self._config = config
        self._crosscheck = CrossCheckEngine(config)
        self._hazard_memory = HazardMemory(config, metrics=metrics)

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
        if not ok_results:
            return FusionOutput(events=[])

        if lane == ToolLane.FAST:
            risk = self._pick_risk(ok_results)
            if risk is None:
                return FusionOutput(events=[])
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
                payload={
                    "riskText": risk.payload.get("riskText", "Obstacle ahead"),
                    "distanceM": risk.payload.get("distanceM"),
                    "azimuthDeg": risk.payload.get("azimuthDeg"),
                    "summary": risk.payload.get("summary", risk.payload.get("riskText", "Obstacle ahead")),
                    "reason": "risk_lane",
                    "activeConfirm": bool(risk.payload.get("activeConfirm", False)),
                    "crosscheckKind": risk.payload.get("crosscheckKind"),
                },
            )
            events = self._apply_hazard_memory(frame, [event])
            return FusionOutput(events=events)

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

        crosscheck = self._crosscheck.evaluate(
            det_result=det,
            depth_result=depth,
            frame_meta=frame.meta.get("frameMeta") if isinstance(frame.meta, dict) else None,
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
        if action_plan is not None and crosscheck.action_patch is not None and health_status.upper() != "SAFE_MODE":
            self._apply_crosscheck_patch(action_plan, crosscheck.action_patch)
            for item in diagnostics:
                if item.get("kind") == crosscheck.action_patch.kind:
                    item["patched"] = True
                    break
        if action_plan is not None:
            events.append(action_plan)
        events = self._apply_hazard_memory(frame, events)
        return FusionOutput(events=events, diagnostics=diagnostics)

    @staticmethod
    def to_legacy_event(event: EventEnvelope) -> dict[str, object | None]:
        payload = event.payload
        if event.type == EventType.RISK:
            return {
                "type": "risk",
                "timestampMs": event.tsEmitMs,
                "coordFrame": event.coordFrame.value,
                "confidence": event.confidence,
                "ttlMs": event.ttlMs,
                "source": event.source,
                "riskText": payload.get("riskText"),
                "summary": payload.get("summary"),
                "distanceM": payload.get("distanceM"),
                "azimuthDeg": payload.get("azimuthDeg"),
                "activeConfirm": payload.get("activeConfirm"),
                "crosscheckKind": payload.get("crosscheckKind"),
                "hazardId": payload.get("hazardId"),
                "hazardKind": payload.get("hazardKind"),
                "hazardState": payload.get("hazardState"),
            }

        if event.type == EventType.PERCEPTION:
            return {
                "type": "perception",
                "timestampMs": event.tsEmitMs,
                "coordFrame": event.coordFrame.value,
                "confidence": event.confidence,
                "ttlMs": event.ttlMs,
                "source": event.source,
                "summary": payload.get("summary"),
                "riskText": None,
                "distanceM": None,
                "azimuthDeg": None,
            }

        if event.type == EventType.ACTION_PLAN:
            return {
                "type": "action_plan",
                "timestampMs": event.tsEmitMs,
                "coordFrame": event.coordFrame.value,
                "confidence": event.confidence,
                "ttlMs": event.ttlMs,
                "source": event.source,
                "summary": payload.get("summary"),
                "actionPlan": payload.get("plan"),
                "speech": payload.get("speech"),
                "hud": payload.get("hud"),
                "activeConfirm": payload.get("activeConfirm"),
                "crosscheckKind": payload.get("crosscheckKind"),
                "riskText": None,
                "distanceM": None,
                "azimuthDeg": None,
            }

        return {
            "type": "health",
            "timestampMs": event.tsEmitMs,
            "coordFrame": event.coordFrame.value,
            "confidence": event.confidence,
            "ttlMs": event.ttlMs,
            "source": event.source,
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
            payload={
                "riskText": f"Potential obstacle: {cls}",
                "distanceM": None,
                "azimuthDeg": self._compute_azimuth_from_meta(frame, top),
                "summary": f"{cls} detected in front",
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
            payload={
                "riskText": f"Depth hazard ahead: {kind}",
                "distanceM": distance_m,
                "azimuthDeg": azimuth_deg,
                "summary": f"{kind} at {distance_m:.2f}m ahead",
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
                "reason": "policy_planner_v0",
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
            payload={
                "riskText": payload.get("riskText", "Cross-check hazard"),
                "distanceM": payload.get("distanceM"),
                "azimuthDeg": payload.get("azimuthDeg"),
                "summary": payload.get("summary", payload.get("riskText", "Cross-check hazard")),
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
