from __future__ import annotations

import math
from dataclasses import dataclass

from byes.config import GatewayConfig
from byes.schema import ActionPlan, ActionStep, ActionType, CoordFrame, EventEnvelope, EventType, ToolResult, ToolStatus
from byes.tools.base import FrameInput, ToolLane


@dataclass
class FusionOutput:
    events: list[EventEnvelope]


class FusionEngine:
    def __init__(self, config: GatewayConfig) -> None:
        self._config = config

    def fuse_lane(
        self,
        frame: FrameInput,
        lane: ToolLane,
        results: list[ToolResult],
        trace_id: str,
        span_id: str,
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
                },
            )
            return FusionOutput(events=[event])

        events: list[EventEnvelope] = []
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

        det = self._pick_det(ok_results)
        risk_semantic = self._risk_from_det(det, frame, trace_id, span_id)
        if risk_semantic is not None:
            events.append(risk_semantic)

        action_plan = self._action_plan_from_semantics(
            frame=frame,
            trace_id=trace_id,
            span_id=span_id,
            perception=perception_event,
            risk=risk_semantic,
        )
        if action_plan is not None:
            events.append(action_plan)
        return FusionOutput(events=events)

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

    def _build_perception_payload(self, results: list[ToolResult]) -> dict[str, object] | None:
        ocr = self._pick_ocr(results)
        det = self._pick_det(results)
        if ocr is None and det is None:
            return None

        if ocr is not None and det is not None:
            confidence = max(0.0, min(1.0, (ocr.confidence * 0.5) + (det.confidence * 0.5)))
            summary = str(ocr.payload.get("text", "")) or str(det.payload.get("summary", "Perception detected"))
            return {
                "confidence": confidence,
                "source": f"{ocr.toolName}@{ocr.toolVersion}",
                "payload": {
                    "summary": summary,
                    "reason": "multi_source_normalized",
                    "detections": det.payload.get("detections", []),
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
                    "riskText": None,
                    "distanceM": None,
                    "azimuthDeg": None,
                },
            }

        assert det is not None
        return {
            "confidence": det.confidence,
            "source": f"{det.toolName}@{det.toolVersion}",
            "payload": {
                "summary": det.payload.get("summary", "Perception detected"),
                "reason": "single_source_det",
                "detections": det.payload.get("detections", []),
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

    def _action_plan_from_semantics(
        self,
        frame: FrameInput,
        trace_id: str,
        span_id: str,
        perception: EventEnvelope | None,
        risk: EventEnvelope | None,
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
            steps = [
                ActionStep(action=ActionType.MOVE, text="Proceed carefully."),
                ActionStep(action=ActionType.CONFIRM, text="Confirm path remains clear."),
            ]
            mode = "assist"
            overall_conf = perception.confidence
            summary = str(perception.payload.get("summary", "Perception updated"))
            speech = f"{summary}. Proceed carefully."
            hud = summary
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
