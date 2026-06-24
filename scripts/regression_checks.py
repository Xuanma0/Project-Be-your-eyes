from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent import AssistanceAgent
from app.planner import Planner

FIND_RED_CAN = "\u5e2e\u6211\u627e\u4e00\u4e0b\u7ea2\u8272\u7684\u7f50\u5b50\u5728\u54ea\u91cc"
REACH_RED_CAN = "\u5f15\u5bfc\u6211\u7684\u624b\u62ff\u8d77\u7ea2\u8272\u7f50\u5b50"
MEDICINE_NAME = "\u836f\u54c1\u540d\u662f\u4ec0\u4e48"
MEDICINE_USAGE = "\u5b83\u662f\u6cbb\u7597\u4ec0\u4e48\u7684"
PACKAGE_PRICE = "\u4e00\u76d2\u6709\u591a\u5c11\u94b1"
RED_CAN = "\u7ea2\u8272\u7f50\u5b50"
CENTER = "\u6b63\u524d\u65b9"
RIGHT_UP = "\u53f3\u4fa7\u4e0a\u65b9"
LEFT_DOWN = "\u5de6\u4e0b\u65b9"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    planner = Planner()
    question = FIND_RED_CAN
    plan = planner._heuristic_plan(question, "ask")
    assert_true(plan["target_zh"] == RED_CAN, "red can target_zh should be preserved")
    assert_true(plan["target_en"] == "can", "red can target_en should be can")
    assert_true(plan["target_color"] == "red", "red can target_color should be red")

    package_plan = planner._heuristic_plan(PACKAGE_PRICE, "ask")
    assert_true(package_plan["intent"] == "visual_question", "open-ended visual questions should collect evidence")
    assert_true(package_plan.get("context_probe") is True, "open-ended visual questions should be marked as context probes")
    assert_true({"detect", "ocr", "memory", "safety"}.issubset(set(package_plan["tools"])), "context probes should run detect, OCR, memory and safety")

    medicine_plan = planner._heuristic_plan(MEDICINE_NAME, "ask")
    assert_true(medicine_plan["intent"] == "read_text", "medicine name questions should route to OCR")
    assert_true("ocr" in medicine_plan["tools"], "medicine name questions should enable OCR")
    assert_true(medicine_plan.get("ocr_focus") == "medicine_name", "medicine OCR should keep focus")
    usage_plan = planner._heuristic_plan(MEDICINE_USAGE, "ask")
    assert_true(usage_plan["intent"] == "read_text", "medicine follow-up questions should route to OCR")
    assert_true(usage_plan.get("ocr_focus") == "medicine_usage", "medicine usage follow-up should keep usage focus")
    medicine_names = planner._extract_medicine_names(["VASOREL", "\u76d0\u9178\u66f2\u7f8e\u4ed6\u55ea\u7247", "Servier (Tianjin) Pharmaceutical Company Limited"])
    assert_true("VASOREL" in medicine_names, "latin medicine brand should be extracted")
    assert_true("\u76d0\u9178\u66f2\u7f8e\u4ed6\u55ea\u7247" in medicine_names, "Chinese generic medicine name should be extracted")
    ocr_items = [
        {"id": "symptom", "type": "text", "text": "\u9002\u5e94\u75c7", "confidence": 1.0, "bbox": [220, 410, 330, 455], "expired": False},
        {"id": "brand", "type": "text", "text": "\u535a\u53f6", "confidence": 0.99, "bbox": [230, 220, 310, 260], "expired": False},
        {"id": "prevention", "type": "text", "text": "\u9884\u9632\u548c\u6cbb\u7597\u8179\u6cfb", "confidence": 0.97, "bbox": [230, 465, 500, 510], "expired": False},
        {"id": "dehydration", "type": "text", "text": "\u5f15\u8d77\u7684\u8f7b\u3001\u4e2d\u5ea6\u8131\u6c34", "confidence": 0.99, "bbox": [230, 510, 510, 555], "expired": False},
        {"id": "title", "type": "text", "text": "\u53e3\u670d\u8865\u6db2\u76d0\u6563\uff08III\uff09", "confidence": 0.94, "bbox": [210, 250, 720, 360], "expired": False},
        {"id": "english", "type": "text", "text": "Oral Rehydration Salts Powder (III)", "confidence": 0.92, "bbox": [210, 360, 740, 410], "expired": False},
    ]
    medicine_answer = planner._read_text_answer(medicine_plan, ocr_items, {"usable": True})
    assert_true("\u53e3\u670d\u8865\u6db2\u76d0\u6563" in medicine_answer["speech"], "medicine title should win over high-confidence indication text")
    usage_answer = planner._read_text_answer(usage_plan, ocr_items, {"usable": True})
    assert_true("\u8179\u6cfb" in usage_answer["speech"] and "\u8131\u6c34" in usage_answer["speech"], "medicine usage should use indication text")

    red_cup = [
        {
            "id": "cup1",
            "type": "object",
            "label": "cup",
            "confidence": 0.85,
            "position": CENTER,
            "attributes": {"color_score": 0.28, "label_zh": "\u676f\u5b50"},
            "expired": False,
        }
    ]
    red_cup_answer = planner._find_answer(plan, red_cup, {"usable": True})
    assert_true(RED_CAN in red_cup_answer["speech"], "red cup surrogate should answer as red can")

    red_carton = [
        {
            "id": "carton1",
            "type": "object",
            "label": "red carton",
            "confidence": 0.22,
            "position": RIGHT_UP,
            "attributes": {"color_score": 0.58, "label_zh": "red carton"},
            "expired": False,
        }
    ]
    weak_answer = planner._find_answer(plan, red_carton, {"usable": True})
    assert_true(f"\u7591\u4f3c{RED_CAN}" in weak_answer["speech"], "red carton should become a weak red can candidate")

    reach_plan = planner._heuristic_plan(REACH_RED_CAN, "auto_assist")
    agent = AssistanceAgent()
    confirmed_target = [
        {
            "id": "target1",
            "type": "object",
            "label": "red can",
            "confidence": 0.88,
            "bbox": [420, 200, 620, 620],
            "position": CENTER,
            "attributes": {"target_match": True, "color_score": 0.55, "label_zh": RED_CAN},
            "expired": False,
        }
    ]
    first = agent.update(REACH_RED_CAN, "auto_assist", reach_plan, confirmed_target, confirmed_target, {"usable": True}, {"blocking": False})
    assert_true(first["agent"]["phase"] == "bring_hand", "confirmed target without hand should ask for hand")

    hand_only = [
        {
            "id": "hand1",
            "type": "hand",
            "label": "hand",
            "confidence": 0.8,
            "bbox": [120, 360, 260, 640],
            "position": LEFT_DOWN,
            "attributes": {"gesture": "open_palm", "gesture_zh": "\u5f20\u5f00\u624b\u638c", "index_tip": [210, 500], "motion": {"label": "steady"}},
            "expired": False,
        }
    ]
    second = agent.update(REACH_RED_CAN, "auto_assist", reach_plan, hand_only, confirmed_target + hand_only, {"usable": True}, {"blocking": False})
    assert_true(second["agent"]["target_locked"], "agent should keep target locked across a brief miss")
    assert_true(second["agent"]["phase"] == "align_hand", "locked target plus visible hand should enter alignment")

    weak_agent = AssistanceAgent()
    weak = weak_agent.update(REACH_RED_CAN, "auto_assist", reach_plan, red_carton, red_carton, {"usable": True}, {"blocking": False})
    assert_true(weak["agent"]["phase"] in {"confirm_target", "search_target"}, "weak target should not go straight to grasping")

    def reach_phase(hand: dict) -> str:
        phase_target = [
            {
                "id": "phase-target",
                "type": "object",
                "label": "red can",
                "confidence": 0.88,
                "bbox": [420, 200, 620, 300],
                "position": CENTER,
                "attributes": {"target_match": True, "color_score": 0.55, "label_zh": RED_CAN},
                "expired": False,
            }
        ]
        local_agent = AssistanceAgent()
        local_agent.update(REACH_RED_CAN, "auto_assist", reach_plan, phase_target, phase_target, {"usable": True}, {"blocking": False})
        result = local_agent.update(
            REACH_RED_CAN,
            "auto_assist",
            reach_plan,
            [hand],
            phase_target + [hand],
            {"usable": True},
            {"blocking": False},
        )
        return result["agent"]["phase"]

    approach_hand = {
        "id": "hand2",
        "type": "hand",
        "label": "hand",
        "confidence": 0.8,
        "bbox": [470, 320, 570, 430],
        "position": CENTER,
        "attributes": {
            "gesture": "open_palm",
            "gesture_zh": "\u5f20\u5f00\u624b\u638c",
            "index_tip": [520, 320],
            "frame_size": [1280, 720],
            "motion": {"label": "steady"},
        },
        "expired": False,
    }
    assert_true(reach_phase(approach_hand) == "approach_target", "aligned but not near hand should approach")

    prepare_hand = {
        **approach_hand,
        "id": "hand3",
        "bbox": [480, 303, 570, 420],
        "attributes": {**approach_hand["attributes"], "index_tip": [520, 303]},
    }
    assert_true(reach_phase(prepare_hand) == "prepare_grasp", "near aligned hand should prepare grasp")

    touch_open = {
        **approach_hand,
        "id": "hand4",
        "bbox": [480, 230, 570, 340],
        "attributes": {**approach_hand["attributes"], "index_tip": [520, 250]},
    }
    assert_true(reach_phase(touch_open) == "close_fingers", "touching open hand should close fingers")

    touch_fist = {
        **touch_open,
        "id": "hand5",
        "attributes": {**touch_open["attributes"], "gesture": "fist", "gesture_zh": "\u63e1\u62f3"},
    }
    assert_true(reach_phase(touch_fist) == "hold", "touching fist should hold")

    lift_hand = {
        **touch_fist,
        "id": "hand6",
        "attributes": {**touch_fist["attributes"], "motion": {"label": "moving_up"}},
    }
    assert_true(reach_phase(lift_hand) == "lift", "touching fist moving up should lift")

    print("regression checks passed")


if __name__ == "__main__":
    main()
