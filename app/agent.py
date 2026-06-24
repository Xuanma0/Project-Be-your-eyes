from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


AUTO_MODES = {"auto_assist", "auto_reach"}


@dataclass
class TaskSession:
    key: str = ""
    goal: str = ""
    intent: str = ""
    phase: str = "idle"
    target_seen_streak: int = 0
    target_miss_streak: int = 0
    hand_seen_streak: int = 0
    last_instruction: str = ""
    last_instruction_at: float = 0.0
    last_phase_at: float = 0.0
    locked_target: Dict[str, Any] = field(default_factory=dict)
    locked_target_at: float = 0.0
    locked_target_kind: str = ""
    locked_target_confidence: float = 0.0
    pending_target_key: str = ""
    pending_target_count: int = 0
    pending_target_at: float = 0.0
    last_hand_target_distance: float = 0.0
    contact_streak: int = 0
    grasp_streak: int = 0
    lift_streak: int = 0
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class AssistanceAgent:
    """Stateful task loop for blind-assistance interactions.

    The planner decides the task and tools; this agent keeps the cross-frame
    state that a one-shot planner cannot provide: stable target, hand presence,
    reach phase, and speech gating.
    """

    def __init__(self) -> None:
        self._session = TaskSession()

    def update(
        self,
        question: str,
        mode: str,
        plan: Dict[str, Any],
        current_evidence: List[Dict[str, Any]],
        recent_evidence: List[Dict[str, Any]],
        quality: Dict[str, Any],
        safety: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = time.time()
        task_key = self._task_key(question, mode, plan)
        if mode not in AUTO_MODES or task_key != self._session.key:
            self._session = TaskSession(
                key=task_key,
                goal=question.strip(),
                intent=str(plan.get("intent") or ""),
                phase="observe",
                started_at=now,
                updated_at=now,
                last_phase_at=now,
            )

        fused = self._fuse_evidence(plan, current_evidence, recent_evidence)
        phase = self._phase(plan, fused, quality, safety)
        if phase != self._session.phase:
            self._session.phase = phase
            self._session.last_phase_at = now

        self._session.intent = str(plan.get("intent") or "")
        self._session.updated_at = now
        self._session.target_seen_streak = (
            self._session.target_seen_streak + 1 if fused["target_current"] else 0
        )
        self._session.target_miss_streak = (
            0 if fused["target_current"] else self._session.target_miss_streak + 1
        )
        self._session.hand_seen_streak = self._session.hand_seen_streak + 1 if fused["hand_current"] else 0
        relation = fused.get("hand_target") or {}
        hand = fused.get("primary_hand") or {}
        hand_attrs = hand.get("attributes") or {}
        gesture = str(hand_attrs.get("gesture") or "")
        motion = (hand_attrs.get("motion") or {}).get("label")
        if relation.get("contact"):
            self._session.contact_streak += 1
        else:
            self._session.contact_streak = 0
        if relation.get("contact") and gesture in {"fist", "pinch"}:
            self._session.grasp_streak += 1
        else:
            self._session.grasp_streak = 0
        if self._session.grasp_streak > 0 and motion == "moving_up":
            self._session.lift_streak += 1
        elif motion != "moving_up":
            self._session.lift_streak = 0

        agent_state = {
            "active": mode in AUTO_MODES,
            "goal": self._session.goal,
            "intent": self._session.intent,
            "phase": self._session.phase,
            "phase_zh": self._phase_zh(self._session.phase),
            "target_seen_streak": self._session.target_seen_streak,
            "target_miss_streak": self._session.target_miss_streak,
            "hand_seen_streak": self._session.hand_seen_streak,
            "stable_target": fused["target_stable"],
            "stable_hand": fused["hand_stable"],
            "target_locked": fused["target_locked"],
            "target_kind": fused["target_kind"],
            "target_position": fused["target_position"],
            "target_confidence": fused["target_confidence"],
            "hand_target": fused["hand_target"],
            "contact_streak": self._session.contact_streak,
            "grasp_streak": self._session.grasp_streak,
            "lift_streak": self._session.lift_streak,
            "should_speak": True,
        }
        plan["agent"] = agent_state
        plan["agent_phase"] = self._session.phase
        return {"evidence": fused["evidence"], "agent": agent_state}

    def refine_answer(
        self,
        answer: Dict[str, Any],
        mode: str,
        agent_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        if mode not in AUTO_MODES:
            return answer

        now = time.time()
        speech = str(answer.get("speech") or "").strip()
        urgent = answer.get("action") == "safety_alert"
        phase = str(agent_state.get("phase") or "")
        repeated = speech and speech == self._session.last_instruction
        phase_age = now - self._session.last_phase_at
        instruction_age = now - self._session.last_instruction_at

        should_speak = True
        if not urgent and repeated and phase_age > 0.8 and instruction_age < 4.8:
            should_speak = False
        if not urgent and phase in {"search_target", "bring_hand"} and repeated and instruction_age < 6.0:
            should_speak = False

        if should_speak and speech:
            self._session.last_instruction = speech
            self._session.last_instruction_at = now

        refined = dict(answer)
        refined["agent"] = dict(agent_state, should_speak=should_speak)
        refined["planner"] = str(refined.get("planner") or "local") + "+agent"
        return refined

    def status(self) -> Dict[str, Any]:
        return {
            "goal": self._session.goal,
            "intent": self._session.intent,
            "phase": self._session.phase,
            "phase_zh": self._phase_zh(self._session.phase),
            "target_seen_streak": self._session.target_seen_streak,
            "target_miss_streak": self._session.target_miss_streak,
            "hand_seen_streak": self._session.hand_seen_streak,
            "target_locked": bool(self._session.locked_target),
            "target_kind": self._session.locked_target_kind,
            "target_confidence": round(self._session.locked_target_confidence, 3),
            "updated_age_ms": round((time.time() - self._session.updated_at) * 1000, 1),
        }

    def reset(self) -> None:
        self._session = TaskSession()

    def _task_key(self, question: str, mode: str, plan: Dict[str, Any]) -> str:
        return "|".join(
            [
                mode,
                str(plan.get("intent") or ""),
                str(plan.get("target_zh") or ""),
                str(plan.get("target_en") or ""),
                str(plan.get("target_color") or ""),
                question.strip(),
            ]
        )

    def _fuse_evidence(
        self,
        plan: Dict[str, Any],
        current_evidence: List[Dict[str, Any]],
        recent_evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        evidence = [copy.deepcopy(item) for item in current_evidence]
        current_ids = {str(item.get("id") or "") for item in current_evidence}
        recent = [item for item in recent_evidence if not item.get("expired")]

        self._mark_weak_candidates(plan, evidence)
        current_objects = [item for item in evidence if item.get("type") == "object"]
        recent_objects = [copy.deepcopy(item) for item in recent if item.get("type") == "object"]
        self._mark_weak_candidates(plan, recent_objects)

        current_targets = [item for item in current_objects if self._is_confirmed_target(plan, item)]
        current_weak_targets = [
            item for item in current_objects if not self._is_confirmed_target(plan, item) and self._is_weak_target(plan, item)
        ]
        recent_targets = [item for item in recent_objects if self._is_confirmed_target(plan, item)]
        recent_weak_targets = [
            item for item in recent_objects if not self._is_confirmed_target(plan, item) and self._is_weak_target(plan, item)
        ]
        current_hands = [item for item in current_evidence if item.get("type") == "hand"]
        recent_hands = [item for item in recent if item.get("type") == "hand"]

        primary_target = self._select_and_lock_target(plan, current_targets, current_weak_targets, current_objects)
        if not primary_target:
            primary_target = self._recover_locked_target(plan, current_objects, recent_targets, recent_weak_targets)
        target_kind = self._target_kind(primary_target)
        stable_target = bool(primary_target)
        stable_hand = bool(current_hands) or (
            bool(recent_hands) and self._session.hand_seen_streak > 0
        )

        if primary_target and str(primary_target.get("id") or "") not in current_ids:
            evidence.insert(0, primary_target)

        for item in evidence:
            if self._is_target_candidate(plan, item):
                attrs = dict(item.get("attributes") or {})
                attrs["stable_count"] = len(recent_targets) + len(recent_weak_targets)
                attrs["current_frame"] = str(item.get("id") or "") in current_ids
                attrs["agent_primary_target"] = (
                    bool(primary_target) and str(item.get("id") or "") == str(primary_target.get("id") or "")
                )
                item["attributes"] = attrs
            elif item.get("type") == "hand":
                attrs = dict(item.get("attributes") or {})
                attrs["stable_count"] = len(recent_hands)
                attrs["current_frame"] = str(item.get("id") or "") in current_ids
                item["attributes"] = attrs

        primary_hand = self._best_hand(current_hands or recent_hands)
        relation = self._hand_target_relation(primary_target, primary_hand)

        return {
            "evidence": evidence,
            "target_current": bool(current_targets or current_weak_targets),
            "hand_current": bool(current_hands),
            "target_stable": stable_target,
            "hand_stable": stable_hand,
            "primary_target": primary_target,
            "primary_hand": primary_hand,
            "target_locked": bool(self._session.locked_target),
            "target_kind": target_kind,
            "target_position": primary_target.get("position") if primary_target else "",
            "target_confidence": round(float(primary_target.get("confidence") or 0.0), 3) if primary_target else 0.0,
            "hand_target": relation,
        }

    def _phase(
        self,
        plan: Dict[str, Any],
        fused: Dict[str, Any],
        quality: Dict[str, Any],
        safety: Dict[str, Any],
    ) -> str:
        if safety.get("blocking"):
            return "safety_hold"
        if not quality.get("usable", True):
            return "reobserve"
        intent = str(plan.get("intent") or "")
        if intent != "guided_reach":
            if intent == "read_text":
                return "read_text"
            if intent == "find_object":
                return "find_object"
            return "observe"

        if not fused["target_stable"]:
            return "search_target"
        if fused.get("target_kind") == "weak":
            return "confirm_target"
        if not fused["hand_stable"]:
            return "bring_hand"

        target = fused.get("primary_target") or next((item for item in fused["evidence"] if self._is_confirmed_target(plan, item)), None)
        hand = fused.get("primary_hand") or next((item for item in fused["evidence"] if item.get("type") == "hand"), None)
        if not target or not hand:
            return "align_hand"
        relation = fused.get("hand_target") or {}
        gesture = str((hand.get("attributes") or {}).get("gesture") or "")
        motion = ((hand.get("attributes") or {}).get("motion") or {}).get("label")
        if relation.get("contact"):
            if gesture in {"fist", "pinch"} and motion == "moving_up":
                return "lift"
            if gesture in {"fist", "pinch"}:
                return "hold"
            return "close_fingers"
        if not relation.get("aligned"):
            return "align_hand"
        if relation.get("near"):
            return "prepare_grasp"
        return "approach_target"

    def _is_target_candidate(self, plan: Dict[str, Any], item: Dict[str, Any]) -> bool:
        return self._is_confirmed_target(plan, item) or self._is_weak_target(plan, item)

    def _is_confirmed_target(self, plan: Dict[str, Any], item: Dict[str, Any]) -> bool:
        if item.get("type") != "object":
            return False
        attrs = item.get("attributes") or {}
        if (
            attrs.get("target_rejected_by")
            or attrs.get("target_color_mismatch")
            or attrs.get("duplicate_of")
            or attrs.get("target_distractor")
        ):
            return False
        if attrs.get("target_match"):
            return True
        target_zh = str(plan.get("target_zh") or "").strip()
        target_en = str(plan.get("target_en") or "").strip().lower()
        target_color = str(plan.get("target_color") or "").strip().lower()
        label = str(item.get("label") or "").lower()
        label_zh = str(item.get("label_zh") or item.get("text") or attrs.get("label_zh") or "")
        if label_zh.startswith("疑似"):
            return False
        if target_en and target_en in label:
            if not target_color:
                return True
            color_score = float(attrs.get("color_score") or 0.0)
            return target_color in label or color_score >= 0.12
        return bool(target_zh and (target_zh in label_zh or label_zh in target_zh))

    def _is_weak_target(self, plan: Dict[str, Any], item: Dict[str, Any]) -> bool:
        if item.get("type") != "object":
            return False
        attrs = item.get("attributes") or {}
        if attrs.get("weak_target_match"):
            return True
        target_en = str(plan.get("target_en") or "").strip().lower()
        target_color = str(plan.get("target_color") or "").strip().lower()
        if target_en != "can" or not target_color:
            return False
        label = str(item.get("label") or "").strip().lower()
        label = label[len(f"{target_color} ") :] if label.startswith(f"{target_color} ") else label
        if label not in {"cup", "mug", "tumbler", "jar", "box", "carton", "bottle"}:
            return False
        return float(attrs.get("color_score") or 0.0) >= 0.25 and float(item.get("confidence") or 0.0) >= 0.08

    def _mark_weak_candidates(self, plan: Dict[str, Any], items: List[Dict[str, Any]]) -> None:
        target_zh = str(plan.get("target_zh") or "").strip()
        for item in items:
            if self._is_confirmed_target(plan, item) or not self._is_weak_target(plan, item):
                continue
            attrs = dict(item.get("attributes") or {})
            attrs["weak_target_match"] = True
            if target_zh:
                attrs["label_zh"] = f"疑似{target_zh}"
            item["attributes"] = attrs

    def _select_and_lock_target(
        self,
        plan: Dict[str, Any],
        confirmed: List[Dict[str, Any]],
        weak: List[Dict[str, Any]],
        current_objects: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        candidates = confirmed or weak
        if not candidates and self._session.locked_target:
            candidates = self._track_locked_by_iou(current_objects)
        if not candidates:
            return {}
        best = copy.deepcopy(max(candidates, key=lambda item: self._target_score(item)))
        kind = "confirmed" if self._is_confirmed_target(plan, best) else "weak"
        if self._should_keep_locked_target(best):
            locked = copy.deepcopy(self._session.locked_target)
            locked["id"] = f"locked-{locked.get('id')}"
            locked["confidence"] = round(float(locked.get("confidence") or 0.0) * 0.78, 3)
            attrs = dict(locked.get("attributes") or {})
            attrs["agent_locked"] = True
            attrs["tracked_from_memory"] = True
            if self._session.locked_target_kind == "confirmed":
                attrs["target_match"] = True
            else:
                attrs["weak_target_match"] = True
            locked["attributes"] = attrs
            return locked
        attrs = dict(best.get("attributes") or {})
        attrs["agent_target_kind"] = kind
        attrs["agent_locked"] = True
        if kind == "confirmed":
            attrs["target_match"] = True
        best["attributes"] = attrs
        self._lock_target(best, kind)
        return best

    def _recover_locked_target(
        self,
        plan: Dict[str, Any],
        current_objects: List[Dict[str, Any]],
        recent_targets: List[Dict[str, Any]],
        recent_weak_targets: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        tracked = self._track_locked_by_iou(current_objects)
        if tracked:
            best = copy.deepcopy(max(tracked, key=lambda item: self._target_score(item)))
            kind = self._session.locked_target_kind or ("confirmed" if self._is_confirmed_target(plan, best) else "weak")
            attrs = dict(best.get("attributes") or {})
            attrs["tracked_from_lock"] = True
            attrs["agent_target_kind"] = kind
            attrs["agent_locked"] = True
            if kind == "confirmed":
                attrs["target_match"] = True
            else:
                attrs["weak_target_match"] = True
            best["attributes"] = attrs
            self._lock_target(best, kind)
            return best
        if self._session.locked_target and time.time() - self._session.locked_target_at <= 2.8:
            locked = copy.deepcopy(self._session.locked_target)
            locked["id"] = f"locked-{locked.get('id')}"
            locked["confidence"] = round(float(locked.get("confidence") or 0.0) * 0.68, 3)
            attrs = dict(locked.get("attributes") or {})
            attrs["tracked_from_memory"] = True
            attrs["agent_locked"] = True
            if self._session.locked_target_kind == "confirmed":
                attrs["target_match"] = True
            else:
                attrs["weak_target_match"] = True
            locked["attributes"] = attrs
            return locked
        recent = recent_targets or recent_weak_targets
        if recent and self._session.target_miss_streak <= 1:
            best = copy.deepcopy(self._best_recent(recent))
            if best:
                kind = "confirmed" if self._is_confirmed_target(plan, best) else "weak"
                best["id"] = f"tracked-{best.get('id')}"
                best["confidence"] = round(float(best.get("confidence") or 0.0) * 0.72, 3)
                attrs = dict(best.get("attributes") or {})
                attrs["tracked_from_memory"] = True
                attrs["agent_target_kind"] = kind
                if kind == "confirmed":
                    attrs["target_match"] = True
                else:
                    attrs["weak_target_match"] = True
                best["attributes"] = attrs
                self._lock_target(best, kind)
                return best
        return {}

    def _track_locked_by_iou(self, current_objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        locked_bbox = self._session.locked_target.get("bbox") if self._session.locked_target else None
        if not locked_bbox:
            return []
        matches = []
        for item in current_objects:
            bbox = item.get("bbox") or []
            if len(bbox) < 4:
                continue
            if self._bbox_iou(locked_bbox, bbox) >= 0.42:
                matches.append(item)
        return matches

    def _lock_target(self, item: Dict[str, Any], kind: str) -> None:
        self._session.locked_target = copy.deepcopy(item)
        self._session.locked_target_at = time.time()
        self._session.locked_target_kind = kind
        self._session.locked_target_confidence = float(item.get("confidence") or 0.0)

    def _should_keep_locked_target(self, candidate: Dict[str, Any]) -> bool:
        locked = self._session.locked_target
        if not locked or not locked.get("bbox") or not candidate.get("bbox"):
            return False
        if time.time() - self._session.locked_target_at > 5.0:
            return False
        iou = self._bbox_iou(locked.get("bbox") or [], candidate.get("bbox") or [])
        distance = self._bbox_center_distance(locked.get("bbox") or [], candidate.get("bbox") or [])
        if iou >= 0.18 or distance <= 0.22:
            self._session.pending_target_key = ""
            self._session.pending_target_count = 0
            return False
        key = self._candidate_key(candidate)
        now = time.time()
        if key and key == self._session.pending_target_key and now - self._session.pending_target_at < 2.0:
            self._session.pending_target_count += 1
        else:
            self._session.pending_target_key = key
            self._session.pending_target_count = 1
        self._session.pending_target_at = now
        candidate_score = self._target_score(candidate)
        locked_score = self._target_score(locked)
        return self._session.pending_target_count < 2 and candidate_score < locked_score + 1.2

    def _candidate_key(self, item: Dict[str, Any]) -> str:
        bbox = item.get("bbox") or []
        if len(bbox) < 4:
            return str(item.get("label") or "")
        cx = (float(bbox[0]) + float(bbox[2])) / 2
        cy = (float(bbox[1]) + float(bbox[3])) / 2
        return f"{item.get('label') or ''}:{round(cx / 120)}:{round(cy / 90)}"

    def _bbox_center_distance(self, a: List[float], b: List[float]) -> float:
        if len(a) < 4 or len(b) < 4:
            return 1.0
        acx = (float(a[0]) + float(a[2])) / 2
        acy = (float(a[1]) + float(a[3])) / 2
        bcx = (float(b[0]) + float(b[2])) / 2
        bcy = (float(b[1]) + float(b[3])) / 2
        width = max(float(a[2]), float(b[2]), 1.0)
        height = max(float(a[3]), float(b[3]), 1.0)
        return (((acx - bcx) / width) ** 2 + ((acy - bcy) / height) ** 2) ** 0.5

    def _target_kind(self, item: Dict[str, Any]) -> str:
        if not item:
            return ""
        attrs = item.get("attributes") or {}
        return str(attrs.get("agent_target_kind") or ("confirmed" if attrs.get("target_match") else "weak"))

    def _target_score(self, item: Dict[str, Any]) -> float:
        attrs = item.get("attributes") or {}
        score = float(item.get("confidence") or 0.0)
        score += 0.55 if attrs.get("target_match") else 0.0
        score += 0.22 if attrs.get("container_surrogate_match") else 0.0
        score += 0.12 if attrs.get("weak_target_match") else 0.0
        score += min(0.35, float(attrs.get("color_score") or 0.0) * 0.35)
        score += min(0.12, float(attrs.get("area_ratio") or 0.0) * 0.5)
        return score

    def _best_recent(self, items: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        if not items:
            return None
        return max(
            items,
            key=lambda item: float(item.get("confidence") or 0.0) - 0.08 * float(item.get("age") or 0.0),
        )

    def _best_hand(self, hands: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not hands:
            return {}
        return max(hands, key=lambda item: float(item.get("confidence") or 0.0))

    def _hand_target_relation(self, target: Dict[str, Any], hand: Dict[str, Any]) -> Dict[str, Any]:
        if not target or not hand:
            return {}
        target_center = self._bbox_center(target.get("bbox"))
        hand_point = self._hand_point(hand)
        if target_center == (0.0, 0.0) or hand_point == (0.0, 0.0):
            return {}
        frame_w, frame_h = self._frame_size(target, hand)
        dx = target_center[0] - hand_point[0]
        dy = target_center[1] - hand_point[1]
        norm_dx = dx / max(1.0, frame_w)
        norm_dy = dy / max(1.0, frame_h)
        distance = (norm_dx * norm_dx + norm_dy * norm_dy) ** 0.5
        moves = []
        if abs(norm_dx) > 0.08:
            moves.append("right" if dx > 0 else "left")
        if abs(norm_dy) > 0.10:
            moves.append("down" if dy > 0 else "up")
        target_attrs = target.get("attributes") or {}
        hand_attrs = hand.get("attributes") or {}
        target_depth = self._as_float(target_attrs.get("depth_proximity"))
        hand_depth = self._as_float(hand_attrs.get("depth_proximity"))
        has_depth = target_depth is not None and hand_depth is not None
        depth_gap = abs(target_depth - hand_depth) if has_depth else None
        same_depth_layer = bool(not has_depth or depth_gap <= 0.22)
        contact_2d = self._touching(target, hand)
        contact = bool(contact_2d and same_depth_layer)
        previous = self._session.last_hand_target_distance
        distance_delta = distance - previous if previous > 0 else 0.0
        self._session.last_hand_target_distance = distance
        move_zh = [self._move_zh(item) for item in moves]
        return {
            "dx": round(dx, 1),
            "dy": round(dy, 1),
            "norm_dx": round(norm_dx, 3),
            "norm_dy": round(norm_dy, 3),
            "distance": round(distance, 3),
            "distance_delta": round(distance_delta, 3),
            "closing": bool(previous > 0 and distance_delta < -0.025),
            "moving_away": bool(previous > 0 and distance_delta > 0.035),
            "aligned": not moves,
            "near": bool(distance <= 0.075 and same_depth_layer),
            "contact": contact,
            "contact_2d": contact_2d,
            "depth_gap": round(depth_gap, 3) if depth_gap is not None else None,
            "same_depth_layer": same_depth_layer,
            "hand_nearer": bool(has_depth and hand_depth > target_depth + 0.08),
            "move": moves,
            "move_zh": move_zh,
        }

    def _touching(self, target: Dict[str, Any], hand: Dict[str, Any]) -> bool:
        target_bbox = target.get("bbox") or []
        hand_bbox = hand.get("bbox") or []
        if len(target_bbox) < 4 or len(hand_bbox) < 4:
            return False
        inter = self._intersection(target_bbox, hand_bbox)
        hand_area = max(1.0, self._area(hand_bbox))
        if inter / hand_area >= 0.08:
            return True
        attrs = hand.get("attributes") or {}
        point = attrs.get("index_tip") or attrs.get("thumb_tip") or attrs.get("palm_center")
        if isinstance(point, list) and len(point) >= 2:
            x, y = float(point[0]), float(point[1])
            return float(target_bbox[0]) <= x <= float(target_bbox[2]) and float(target_bbox[1]) <= y <= float(target_bbox[3])
        return False

    def _intersection(self, a: List[float], b: List[float]) -> float:
        x1 = max(float(a[0]), float(b[0]))
        y1 = max(float(a[1]), float(b[1]))
        x2 = min(float(a[2]), float(b[2]))
        y2 = min(float(a[3]), float(b[3]))
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def _area(self, bbox: List[float]) -> float:
        return max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1]))

    def _as_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _bbox_iou(self, a: List[float], b: List[float]) -> float:
        inter = self._intersection(a, b)
        union = self._area(a) + self._area(b) - inter
        if union <= 0:
            return 0.0
        return inter / union

    def _bbox_center(self, bbox: Any) -> Tuple[float, float]:
        if isinstance(bbox, list) and len(bbox) >= 4:
            return (float(bbox[0] + bbox[2]) / 2.0, float(bbox[1] + bbox[3]) / 2.0)
        return (0.0, 0.0)

    def _hand_point(self, hand: Dict[str, Any]) -> Tuple[float, float]:
        attrs = hand.get("attributes") or {}
        point = attrs.get("index_tip") or attrs.get("palm_center")
        if isinstance(point, list) and len(point) >= 2:
            return (float(point[0]), float(point[1]))
        return self._bbox_center(hand.get("bbox"))

    def _frame_size(self, *items: Dict[str, Any]) -> Tuple[float, float]:
        max_x = 1280.0
        max_y = 720.0
        for item in items:
            attrs = item.get("attributes") or {}
            frame_size = attrs.get("frame_size")
            if isinstance(frame_size, list) and len(frame_size) >= 2:
                max_x = max(max_x, float(frame_size[0]))
                max_y = max(max_y, float(frame_size[1]))
        for item in items:
            bbox = item.get("bbox") or []
            if isinstance(bbox, list) and len(bbox) >= 4:
                max_x = max(max_x, float(bbox[2]))
                max_y = max(max_y, float(bbox[3]))
        return max_x, max_y

    def _move_zh(self, move: str) -> str:
        return {
            "left": "向左",
            "right": "向右",
            "up": "向上",
            "down": "向下",
        }.get(move, move)

    def _phase_zh(self, phase: str) -> str:
        return {
            "idle": "待命",
            "observe": "观察",
            "reobserve": "重观察",
            "safety_hold": "安全暂停",
            "search_target": "搜索目标",
            "confirm_target": "确认目标",
            "bring_hand": "等待手进入",
            "align_hand": "对准手",
            "approach_target": "靠近目标",
            "prepare_grasp": "准备抓取",
            "close_fingers": "收拢手指",
            "grasp": "抓取",
            "hold": "握住",
            "lift": "抬起",
            "find_object": "找物",
            "read_text": "读字",
        }.get(phase, phase)
