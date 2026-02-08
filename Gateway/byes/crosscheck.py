from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from byes.config import GatewayConfig
from byes.schema import HealthStatus, ToolResult


@dataclass(frozen=True)
class CrossCheckActionPatch:
    kind: str
    summary: str
    speech: str
    hud: str
    steps: list[dict[str, Any]]
    active_confirm: bool = True


@dataclass(frozen=True)
class CrossCheckDiagnostic:
    kind: str
    details: dict[str, Any] = field(default_factory=dict)
    active_confirm: bool = False
    patched: bool = False


@dataclass(frozen=True)
class CrossCheckResult:
    risks: list[dict[str, Any]] = field(default_factory=list)
    action_patch: CrossCheckActionPatch | None = None
    diagnostics: list[CrossCheckDiagnostic] = field(default_factory=list)


class CrossCheckEngine:
    """Lightweight O(n) multi-modal consistency checks with cooldown."""

    KIND_VISION_WITHOUT_DEPTH = "vision_without_depth"
    KIND_DEPTH_WITHOUT_VISION = "depth_without_vision"

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._cooldown_ms = max(0, int(config.crosscheck_cooldown_ms))
        self._transparent_aliases = {
            item.strip().lower()
            for item in str(config.crosscheck_transparent_aliases_csv).split(",")
            if item.strip()
        }
        self._last_trigger_by_session_kind: dict[tuple[str, str], int] = {}

    def evaluate(
        self,
        *,
        det_result: ToolResult | None,
        depth_result: ToolResult | None,
        frame_meta: dict[str, Any] | None,
        health_status: str,
        session_id: str,
        now_ms: int | None = None,
    ) -> CrossCheckResult:
        current_ms = int(now_ms) if now_ms is not None else int(time.time() * 1000)
        normalized_session = session_id.strip() if session_id else "default"
        normalized_health = str(health_status or HealthStatus.NORMAL.value).strip().upper()

        detections = _extract_detections(det_result)
        hazards = _extract_hazards(depth_result)
        min_depth_distance = _min_distance(hazards)
        det_conf = _max_detection_confidence(detections)
        has_transparent_like_det = any(
            _contains_any(str(item.get("class", "")), self._transparent_aliases) for item in detections
        )
        has_explainable_det = any(float(item.get("confidence", 0.0)) >= self._config.crosscheck_det_low_conf_threshold for item in detections)

        risks: list[dict[str, Any]] = []
        diagnostics: list[CrossCheckDiagnostic] = []
        action_patch: CrossCheckActionPatch | None = None

        forced_kind = ""
        if isinstance(frame_meta, dict):
            forced_kind = str(frame_meta.get("forceCrosscheckKind", "")).strip()
        if forced_kind in {self.KIND_VISION_WITHOUT_DEPTH, self.KIND_DEPTH_WITHOUT_VISION}:
            if self._allow_emit(forced_kind, normalized_session, current_ms):
                risk_payload, action_patch = self._build_forced_conflict(
                    kind=forced_kind,
                    min_depth_distance=min_depth_distance,
                    hazards=hazards,
                    health_status=normalized_health,
                )
                risks.append(risk_payload)
                diagnostics.append(
                    CrossCheckDiagnostic(
                        kind=forced_kind,
                        details={"forced": True, "detConfidence": det_conf, "minDepthDistanceM": min_depth_distance},
                        active_confirm=True,
                        patched=False,
                    )
                )
            return CrossCheckResult(risks=risks, action_patch=action_patch, diagnostics=diagnostics)

        # A) Det sees likely transparent obstacle but depth misses.
        if has_transparent_like_det and (
            not hazards
            or min_depth_distance is None
            or min_depth_distance > float(self._config.crosscheck_depth_far_threshold_m)
        ):
            if self._allow_emit(self.KIND_VISION_WITHOUT_DEPTH, normalized_session, current_ms):
                risk_payload = {
                    "riskText": "Possible transparent obstacle ahead. Please confirm before moving.",
                    "summary": "Active confirm: possible transparent obstacle, stop and scan.",
                    "distanceM": min_depth_distance,
                    "azimuthDeg": 0.0,
                    "severity": "warning",
                    "reason": "crosscheck",
                    "crosscheckKind": self.KIND_VISION_WITHOUT_DEPTH,
                    "activeConfirm": True,
                }
                risks.append(risk_payload)
                diagnostics.append(
                    CrossCheckDiagnostic(
                        kind=self.KIND_VISION_WITHOUT_DEPTH,
                        details={"detConfidence": det_conf, "minDepthDistanceM": min_depth_distance},
                        active_confirm=True,
                        patched=False,
                    )
                )
                if normalized_health != HealthStatus.SAFE_MODE.value:
                    action_patch = CrossCheckActionPatch(
                        kind=self.KIND_VISION_WITHOUT_DEPTH,
                        summary="Active confirm required: transparent obstacle candidate.",
                        speech="Transparent obstacle possible. Stop and scan left and right before moving.",
                        hud="Stop and scan (transparent obstacle check)",
                        steps=[
                            {"action": "stop", "text": "Stop immediately."},
                            {"action": "scan", "text": "Small head scan left and right."},
                            {"action": "confirm", "text": "Confirm clear path before move/turn."},
                        ],
                        active_confirm=True,
                    )

        # B) Depth sees near hazard but vision misses.
        if not risks and hazards and min_depth_distance is not None and min_depth_distance < float(
            self._config.crosscheck_depth_near_threshold_m
        ):
            if not has_explainable_det or det_conf < float(self._config.crosscheck_det_low_conf_threshold):
                if self._allow_emit(self.KIND_DEPTH_WITHOUT_VISION, normalized_session, current_ms):
                    nearest_kind = str(_nearest_hazard_kind(hazards))
                    severity = "critical" if nearest_kind in {"dropoff", "pit", "stairs_down"} else "warning"
                    risk_payload = {
                        "riskText": "Depth hazard detected without visual confirmation.",
                        "summary": "Active confirm: depth hazard ahead, stop and scan environment.",
                        "distanceM": min_depth_distance,
                        "azimuthDeg": float(hazards[0].get("azimuthDeg", 0.0)) if hazards else 0.0,
                        "severity": severity,
                        "reason": "crosscheck",
                        "crosscheckKind": self.KIND_DEPTH_WITHOUT_VISION,
                        "activeConfirm": True,
                    }
                    risks.append(risk_payload)
                    diagnostics.append(
                        CrossCheckDiagnostic(
                            kind=self.KIND_DEPTH_WITHOUT_VISION,
                            details={"detConfidence": det_conf, "minDepthDistanceM": min_depth_distance, "hazardKind": nearest_kind},
                            active_confirm=True,
                            patched=False,
                        )
                    )
                    if normalized_health != HealthStatus.SAFE_MODE.value:
                        action_patch = CrossCheckActionPatch(
                            kind=self.KIND_DEPTH_WITHOUT_VISION,
                            summary="Active confirm required: depth-only hazard.",
                            speech="Depth hazard ahead. Stop and scan surroundings before any turn or move.",
                            hud="Depth hazard: stop and scan environment",
                            steps=[
                                {"action": "stop", "text": "Stop immediately."},
                                {"action": "scan", "text": "Scan environment for drop-offs/obstacles."},
                                {"action": "confirm", "text": "Confirm safe route before moving."},
                            ],
                            active_confirm=True,
                        )

        return CrossCheckResult(risks=risks, action_patch=action_patch, diagnostics=diagnostics)

    def _allow_emit(self, kind: str, session_id: str, now_ms: int) -> bool:
        if self._cooldown_ms <= 0:
            return True
        key = (session_id, kind)
        last_ms = self._last_trigger_by_session_kind.get(key, -1)
        if last_ms >= 0 and (now_ms - last_ms) < self._cooldown_ms:
            return False
        self._last_trigger_by_session_kind[key] = now_ms
        return True

    def reset_runtime(self) -> None:
        self._last_trigger_by_session_kind.clear()

    def _build_forced_conflict(
        self,
        *,
        kind: str,
        min_depth_distance: float | None,
        hazards: list[dict[str, Any]],
        health_status: str,
    ) -> tuple[dict[str, Any], CrossCheckActionPatch | None]:
        if kind == self.KIND_VISION_WITHOUT_DEPTH:
            risk_payload = {
                "riskText": "Possible transparent obstacle ahead. Please confirm before moving.",
                "summary": "Active confirm: possible transparent obstacle, stop and scan.",
                "distanceM": min_depth_distance,
                "azimuthDeg": 0.0,
                "severity": "warning",
                "reason": "crosscheck",
                "crosscheckKind": self.KIND_VISION_WITHOUT_DEPTH,
                "activeConfirm": True,
            }
            patch = None
            if health_status != HealthStatus.SAFE_MODE.value:
                patch = CrossCheckActionPatch(
                    kind=self.KIND_VISION_WITHOUT_DEPTH,
                    summary="Active confirm required: transparent obstacle candidate.",
                    speech="Transparent obstacle possible. Stop and scan left and right before moving.",
                    hud="Stop and scan (transparent obstacle check)",
                    steps=[
                        {"action": "stop", "text": "Stop immediately."},
                        {"action": "scan", "text": "Small head scan left and right."},
                        {"action": "confirm", "text": "Confirm clear path before move/turn."},
                    ],
                    active_confirm=True,
                )
            return risk_payload, patch

        nearest_kind = str(_nearest_hazard_kind(hazards))
        severity = "critical" if nearest_kind in {"dropoff", "pit", "stairs_down"} else "warning"
        risk_payload = {
            "riskText": "Depth hazard detected without visual confirmation.",
            "summary": "Active confirm: depth hazard ahead, stop and scan environment.",
            "distanceM": min_depth_distance,
            "azimuthDeg": float(hazards[0].get("azimuthDeg", 0.0)) if hazards else 0.0,
            "severity": severity,
            "reason": "crosscheck",
            "crosscheckKind": self.KIND_DEPTH_WITHOUT_VISION,
            "activeConfirm": True,
        }
        patch = None
        if health_status != HealthStatus.SAFE_MODE.value:
            patch = CrossCheckActionPatch(
                kind=self.KIND_DEPTH_WITHOUT_VISION,
                summary="Active confirm required: depth-only hazard.",
                speech="Depth hazard ahead. Stop and scan surroundings before any turn or move.",
                hud="Depth hazard: stop and scan environment",
                steps=[
                    {"action": "stop", "text": "Stop immediately."},
                    {"action": "scan", "text": "Scan environment for drop-offs/obstacles."},
                    {"action": "confirm", "text": "Confirm safe route before moving."},
                ],
                active_confirm=True,
            )
        return risk_payload, patch


def _extract_detections(result: ToolResult | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    raw = result.payload.get("detections")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def _extract_hazards(result: ToolResult | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    raw = result.payload.get("hazards")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    out.sort(key=lambda item: float(item.get("distanceM", 9999.0)))
    return out


def _min_distance(hazards: list[dict[str, Any]]) -> float | None:
    if not hazards:
        return None
    values: list[float] = []
    for item in hazards:
        try:
            values.append(float(item.get("distanceM")))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return min(values)


def _max_detection_confidence(detections: list[dict[str, Any]]) -> float:
    confs: list[float] = []
    for item in detections:
        try:
            confs.append(float(item.get("confidence", 0.0)))
        except (TypeError, ValueError):
            continue
    if not confs:
        return 0.0
    return max(confs)


def _contains_any(value: str, aliases: set[str]) -> bool:
    normalized = str(value).strip().lower()
    if not normalized:
        return False
    return any(alias in normalized for alias in aliases)


def _nearest_hazard_kind(hazards: list[dict[str, Any]]) -> str:
    if not hazards:
        return "hazard"
    nearest = hazards[0]
    return str(nearest.get("kind", "hazard")).strip().lower() or "hazard"
