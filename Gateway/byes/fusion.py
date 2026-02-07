from __future__ import annotations

from dataclasses import dataclass

from byes.config import GatewayConfig
from byes.schema import CoordFrame, EventEnvelope, EventType, ToolResult, ToolStatus
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

        ocr = self._pick_ocr(ok_results)
        if ocr is None:
            return FusionOutput(events=[])

        confidence = ocr.confidence
        reason = "single_source"
        if len(ok_results) > 1:
            confidence = confidence * 0.9
            reason = "multi_source_normalized"

        event = EventEnvelope(
            type=EventType.PERCEPTION,
            traceId=trace_id,
            spanId=span_id,
            seq=frame.seq,
            tsCaptureMs=frame.ts_capture_ms,
            ttlMs=frame.ttl_ms,
            coordFrame=CoordFrame.WORLD,
            confidence=confidence,
            priority=self._config.perception_priority,
            source=f"{ocr.toolName}@{ocr.toolVersion}",
            payload={
                "summary": ocr.payload.get("text", "Perception detected"),
                "reason": reason,
                "riskText": None,
                "distanceM": None,
                "azimuthDeg": None,
            },
        )
        return FusionOutput(events=[event])

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

        return {
            "type": "health",
            "timestampMs": event.tsEmitMs,
            "coordFrame": event.coordFrame.value,
            "confidence": event.confidence,
            "ttlMs": event.ttlMs,
            "source": event.source,
            "summary": payload.get("status", "health"),
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
