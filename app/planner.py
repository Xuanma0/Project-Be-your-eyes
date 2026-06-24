from __future__ import annotations

import json
import copy
import re
import time
from typing import Any, Dict, List

from openai import OpenAI

from .config import settings


TOOL_SET = {"detect", "hand", "ocr", "safety", "memory"}
HAND_ACTION_WORDS = ["拿", "抓", "够到", "摸到", "伸手", "拿起", "抓住", "取到", "拿到", "引导我的手", "引导手"]
GESTURE_WORDS = ["手势", "手部动作", "我的手", "手在", "拳头", "握拳", "张开", "捏", "捏合", "指向", "手指", "比划"]
SPATIAL_RELATION_WORDS = ["什么位置", "相对", "旁边", "左边", "右边", "上方", "下方"]
OCR_WORDS = ["读", "文字", "牌", "屏幕", "标签", "名字", "名称", "书名", "标题", "写着", "上面写"]
MEDICINE_NAME_WORDS = [
    "药品名",
    "药名",
    "药叫什么",
    "这是什么药",
    "这个药",
    "药的名字",
    "药的名称",
    "药盒上",
    "药板上",
    "药片上",
]
MEDICINE_USAGE_WORDS = [
    "治疗什么",
    "治什么",
    "治疗啥",
    "治啥",
    "适应症",
    "用于什么",
    "有什么用",
    "什么作用",
    "作用是什么",
    "功效",
    "干什么的",
]
MEDICINE_DOSAGE_WORDS = [
    "怎么吃",
    "怎么服用",
    "用法",
    "用量",
    "一次几",
    "一天几",
    "服法",
]
MEDICINE_INGREDIENT_WORDS = [
    "成分",
    "含什么",
    "补充什么",
    "里面有什么",
]
MEDICINE_FORM_WORDS = [
    "片",
    "胶囊",
    "颗粒",
    "丸",
    "口服液",
    "注射液",
    "滴眼液",
    "乳膏",
    "软膏",
    "凝胶",
    "糖浆",
    "散",
    "贴",
]
MEDICINE_LATIN_BLACKLIST = {
    "COMPANY",
    "LIMITED",
    "PHARMACEUTICAL",
    "TABLETS",
    "HYDROCHLORIDE",
    "CHINA",
    "SERVIER",
}

TARGET_MAP = {
    "杯": "cup",
    "水杯": "cup",
    "杯子": "cup",
    "瓶": "bottle",
    "瓶子": "bottle",
    "罐": "can",
    "罐子": "can",
    "易拉罐": "can",
    "铁罐": "can",
    "咖啡罐": "can",
    "手机": "cell phone",
    "电脑": "laptop",
    "键盘": "keyboard",
    "鼠标": "mouse",
    "书": "book",
    "椅子": "chair",
    "门": "door",
    "人": "person",
    "背包": "backpack",
    "包": "backpack",
    "遥控器": "remote",
    "门把手": "door handle",
    "把手": "handle",
    "楼梯": "stairs",
    "台阶": "stairs",
    "阶梯": "stairs",
    "盲道": "tactile paving",
    "药盒": "medicine box",
    "药瓶": "medicine bottle",
    "药": "medicine",
    "钥匙": "key",
    "钱包": "wallet",
    "卡": "card",
    "身份证": "ID card",
    "插座": "power outlet",
    "充电器": "charger",
    "电线": "cable",
    "线": "cable",
    "耳机": "earphones",
    "眼镜": "glasses",
    "垃圾桶": "trash can",
    "路障": "barrier",
    "障碍物": "obstacle",
    "地毯": "rug",
    "垫子": "mat",
    "门口": "doorway",
    "电梯": "elevator",
    "按钮": "button",
    "出口": "exit sign",
    "斑马线": "crosswalk",
    "红绿灯": "traffic light",
    "盲杖": "white cane",
    "拐杖": "cane",
}

TARGET_CLASS_ALIASES = {
    "cup": {"cup", "wine glass"},
    "cell phone": {"cell phone", "remote"},
    "stairs": {"stairs", "stair", "steps", "step"},
    "door handle": {"door handle", "handle", "doorknob"},
    "key": {"key", "keys"},
    "wallet": {"wallet", "purse"},
    "power outlet": {"power outlet", "socket", "outlet"},
    "trash can": {"trash can", "bin", "garbage can"},
    "can": {"can", "tin can", "food can", "snack can"},
}

TARGET_PROMPT_ALIASES = {
    "cup": ["cup", "mug", "drinking cup", "tumbler"],
    "door handle": ["door handle", "doorknob", "handle"],
    "stairs": ["stairs", "steps", "staircase"],
    "tactile paving": ["tactile paving", "blind sidewalk", "guiding block"],
    "medicine box": ["medicine box", "pill box", "medicine package"],
    "medicine bottle": ["medicine bottle", "pill bottle"],
    "key": ["key", "keys"],
    "wallet": ["wallet", "purse"],
    "power outlet": ["power outlet", "electrical socket", "socket"],
    "charger": ["charger", "power adapter"],
    "cable": ["cable", "wire"],
    "trash can": ["trash can", "bin", "garbage can"],
    "can": ["can", "tin can", "food can", "snack can", "cylindrical can"],
    "crosswalk": ["crosswalk", "zebra crossing"],
    "traffic light": ["traffic light", "pedestrian light"],
    "white cane": ["white cane", "cane"],
}

COLOR_WORDS = {
    "红色": ("红色", "red"),
    "红": ("红色", "red"),
    "绿色": ("绿色", "green"),
    "绿": ("绿色", "green"),
    "蓝色": ("蓝色", "blue"),
    "蓝": ("蓝色", "blue"),
    "黄色": ("黄色", "yellow"),
    "黄": ("黄色", "yellow"),
    "黑色": ("黑色", "black"),
    "黑": ("黑色", "black"),
    "白色": ("白色", "white"),
    "白": ("白色", "white"),
}


class Planner:
    def __init__(self) -> None:
        self.enabled = bool(settings.deepseek_api_key and settings.deepseek_api_key != "sk-your-key-here")
        self.client = (
            OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
            if self.enabled
            else None
        )
        self._target_cache: Dict[str, Dict[str, Any]] = {}
        self._plan_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}

    def plan_tools(self, question: str, mode: str) -> Dict[str, Any]:
        cache_key = self._plan_cache_key(question, mode)
        if mode in {"auto_assist", "auto_reach"}:
            cached = self._plan_cache.get(cache_key)
            if cached and time.time() - cached[0] < 600:
                plan = copy.deepcopy(cached[1])
                plan["cache_hit"] = True
                return plan

        fallback = self._heuristic_plan(question, mode)
        if str(fallback.get("ocr_focus") or "").startswith("medicine_"):
            self._cache_plan(cache_key, mode, fallback)
            return fallback
        if fallback.get("intent") == "spatial_relation":
            self._cache_plan(cache_key, mode, fallback)
            return fallback
        if fallback.get("intent") == "hand_status":
            self._cache_plan(cache_key, mode, fallback)
            return fallback
        if not self.enabled or not settings.enable_deepseek_tool_planner or mode in {"safety", "auto_safety"}:
            self._cache_plan(cache_key, mode, fallback)
            return fallback

        prompt = {
            "question": question,
            "mode": mode,
            "available_tools": sorted(TOOL_SET),
            "instruction": (
                "Classify the user's task for a blind egocentric assistance system. "
                "Return JSON only. Do not ask for image pixels."
            ),
        }
        try:
            assert self.client is not None
            response = self.client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a tool planner. Return compact JSON with keys: "
                            "intent, tools, target_zh, target_en, target_color, target_color_zh, target_prompts, safety_priority. "
                            "tools must be chosen from detect, hand, ocr, safety, memory. "
                            "Use intent guided_reach and include hand when the user wants to reach, grab, or pick up an object."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                max_tokens=220,
            )
            parsed = self._loads_json(response.choices[0].message.content or "{}")
            tools = [tool for tool in parsed.get("tools", []) if tool in TOOL_SET]
            if not tools:
                tools = fallback["tools"]
            tools = self._normalize_tools(tools, mode, question)
            intent = str(parsed.get("intent") or fallback["intent"])
            if self._needs_hand_guidance(question) and fallback.get("target_en"):
                intent = "guided_reach"
            fallback_target_zh = str(fallback.get("target_zh") or "")
            fallback_target_en = str(fallback.get("target_en") or "")
            target_zh = str(parsed.get("target_zh") or fallback_target_zh or "")
            target_en = str(parsed.get("target_en") or fallback_target_en or "")
            target_color = str(parsed.get("target_color") or fallback.get("target_color") or "")
            target_color_zh = str(parsed.get("target_color_zh") or fallback.get("target_color_zh") or "")
            if fallback_target_zh and fallback_target_en:
                target_zh = fallback_target_zh
                target_en = fallback_target_en
                target_color = str(fallback.get("target_color") or target_color)
                target_color_zh = str(fallback.get("target_color_zh") or target_color_zh)
            if target_zh and target_color_zh and target_color_zh not in target_zh:
                object_zh = self._strip_color_words(target_zh)
                target_zh = f"{target_color_zh}{object_zh}"
            plan = {
                "intent": intent,
                "tools": tools,
                "target_zh": target_zh,
                "target_en": target_en,
                "target_color": target_color,
                "target_color_zh": target_color_zh,
                "target_prompts": fallback.get("target_prompts", []) if fallback_target_zh else parsed.get("target_prompts") or fallback.get("target_prompts", []),
                "safety_priority": bool(parsed.get("safety_priority", fallback["safety_priority"])),
                "mode": mode,
                "planner": "deepseek",
            }
            plan = self._apply_context_probe(plan, question, mode)
            self._cache_plan(cache_key, mode, plan)
            return plan
        except Exception as exc:
            fallback["planner"] = "heuristic"
            fallback["planner_error"] = repr(exc)
            self._cache_plan(cache_key, mode, fallback)
            return fallback

    def _plan_cache_key(self, question: str, mode: str) -> str:
        return f"{mode}:{question.strip().lower()}"

    def _cache_plan(self, cache_key: str, mode: str, plan: Dict[str, Any]) -> None:
        if mode not in {"auto_assist", "auto_reach"}:
            return
        self._plan_cache[cache_key] = (time.time(), copy.deepcopy(plan))

    def compose_answer(
        self,
        question: str,
        mode: str,
        plan: Dict[str, Any],
        current_evidence: List[Dict[str, Any]],
        memory: List[Dict[str, Any]],
        safety: Dict[str, Any],
        quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        if safety.get("blocking") and (
            not quality.get("usable", True)
            or mode in {"safety", "auto_safety"}
            or mode in {"reach", "auto_reach", "auto_assist"}
            or plan.get("intent") == "safety"
        ):
            return {
                "action": "safety_alert",
                "speech": safety.get("speech") or "请先停一下，当前画面存在不确定风险。",
                "confidence": safety.get("confidence", 0.6),
                "used_evidence_ids": safety.get("evidence_ids", []),
                "planner": "safety_gate",
            }

        if mode in {"safety", "auto_safety"}:
            return self._safety_answer(safety, quality)

        if plan.get("intent") == "read_text":
            return self._read_text_answer(plan, current_evidence, quality)
        if plan.get("intent") == "hand_status":
            return self._hand_status_answer(current_evidence, quality)

        if mode == "ocr" and not any(e.get("type") == "text" and not e.get("expired") for e in current_evidence):
            return {
                "action": "reobserve",
                "speech": "我还没有读到清晰文字，请把文字放到画面中间，靠近一点并保持稳定。",
                "confidence": 0.5,
                "used_evidence_ids": [e.get("id") for e in current_evidence if e.get("type") == "tool_status"],
                "planner": "local_ocr_gate",
            }

        if plan.get("intent") == "guided_reach":
            return self._guided_reach_answer(plan, current_evidence, quality)
        if plan.get("intent") == "spatial_relation":
            return self._spatial_relation_answer(plan, current_evidence, quality)
        if plan.get("intent") == "find_object":
            return self._find_answer(plan, current_evidence, quality)

        fallback = self._fallback_answer(question, current_evidence, memory, quality)
        if mode == "find":
            return self._find_answer(plan, current_evidence, quality)
        if mode == "memory":
            return self._memory_answer(memory)
        if mode in {"describe", "find", "ocr", "memory"}:
            fallback["planner"] = f"local_{mode}"
            return fallback
        if not self.enabled:
            return fallback

        payload = {
            "question": question,
            "mode": mode,
            "plan": plan,
            "quality": quality,
            "safety": safety,
            "current_evidence": current_evidence[:80],
            "memory": memory[-80:],
            "rules": [
                "The assistant cannot see the image directly.",
                "Use only the provided evidence.",
                "Do not say the path is safe. Say what evidence was or was not detected.",
                "If evidence is insufficient, return action reobserve and ask for a small camera movement.",
                "If the frame is blurry, dark, or obstructed, ask the user to stop and re-observe.",
            ],
        }
        try:
            assert self.client is not None
            response = self.client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the text planner for a blind visual assistance prototype. "
                            "Return JSON only with keys: action, speech, confidence, used_evidence_ids. "
                            "action is answer, reobserve, refuse_uncertain, or safety_alert. "
                            "Use concise Chinese speech suitable for headphones."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                max_tokens=360,
            )
            parsed = self._loads_json(response.choices[0].message.content or "{}")
            speech = str(parsed.get("speech") or fallback["speech"]).strip()
            action = str(parsed.get("action") or fallback["action"]).strip()
            if action not in {"answer", "reobserve", "refuse_uncertain", "safety_alert"}:
                action = fallback["action"]
            return {
                "action": action,
                "speech": speech[:500],
                "confidence": float(parsed.get("confidence", fallback["confidence"])),
                "used_evidence_ids": parsed.get("used_evidence_ids", []),
                "planner": "deepseek",
            }
        except Exception as exc:
            fallback["planner_error"] = repr(exc)
            return fallback

    def _heuristic_plan(self, question: str, mode: str) -> Dict[str, Any]:
        q = question.strip()
        tools = {"safety"}
        intent = "describe"

        if mode == "describe":
            tools.add("detect")
            return self._plan_result("describe", tools, "", "", mode, q)
        if mode == "ocr":
            tools.add("ocr")
            return self._plan_result("read_text", tools, "", "", mode, q)
        if mode == "memory":
            tools.update({"detect", "memory"})
            return self._plan_result("memory", tools, "", "", mode, q)
        if mode in {"safety", "auto_safety"}:
            tools.add("detect")
            return self._plan_result("safety", tools, "", "", mode, q)
        if mode in {"reach", "auto_reach"}:
            target_zh = self._extract_target(q) or "红色罐子"
            target_info = self._resolve_target(target_zh)
            tools.update({"detect", "hand", "safety"})
            return self._plan_result(
                "guided_reach",
                tools,
                target_info["target_zh"],
                target_info["target_en"],
                mode,
                q,
                target_info["target_prompts"],
                target_info.get("target_color", ""),
                target_info.get("target_color_zh", ""),
            )
        if mode == "gesture" or (any(word in q for word in GESTURE_WORDS) and not self._needs_hand_guidance(q)):
            tools.add("hand")
            return self._plan_result("hand_status", tools, "", "", mode, q)

        relation = self._parse_spatial_relation(q)
        if relation:
            tools.add("detect")
            prompts = self._relation_prompts(relation)
            plan = self._plan_result(
                "spatial_relation",
                tools,
                "",
                "can" if all(item.get("target_en") == "can" for item in relation.values()) else "",
                mode,
                q,
                prompts,
            )
            plan["relation"] = relation
            return plan

        medicine_focus = self._medicine_ocr_focus(q)
        if medicine_focus:
            tools.update({"ocr", "memory"})
            plan = self._plan_result("read_text", tools, "", "", mode, q)
            plan["ocr_focus"] = medicine_focus
            return plan

        if mode == "find":
            target_zh = self._extract_target(q) or "水杯"
            target_info = self._resolve_target(target_zh)
            tools.add("detect")
            if self._needs_hand_guidance(q):
                tools.add("hand")
            return self._plan_result(
                "guided_reach" if self._needs_hand_guidance(q) else "find_object",
                tools,
                target_info["target_zh"],
                target_info["target_en"],
                mode,
                q,
                target_info["target_prompts"],
                target_info.get("target_color", ""),
                target_info.get("target_color_zh", ""),
            )

        if any(word in q for word in ["什么", "看到", "画面", "前面"]):
            tools.add("detect")
        medicine_focus = self._medicine_ocr_focus(q)
        if mode == "ocr" or any(word in q for word in OCR_WORDS) or medicine_focus:
            tools.add("ocr")
            if any(word in q for word in ["书", "本书", "封面", "标签", "牌", "屏幕"]):
                tools.add("detect")
            intent = "read_text"
        if any(word in q for word in ["刚才", "之前", "记得", "看到过"]):
            tools.add("memory")
            intent = "memory"
        if any(word in q for word in ["安全", "走", "障碍", "危险"]):
            tools.add("safety")
            intent = "safety"
        target_zh = self._extract_target(q) if intent != "memory" else ""
        target_info = (
            self._resolve_target(target_zh)
            if target_zh
            else {"target_zh": "", "target_en": "", "target_prompts": [], "target_color": "", "target_color_zh": ""}
        )
        target_en = target_info["target_en"]
        if target_zh and intent != "read_text":
            tools.add("detect")
            if self._needs_hand_guidance(q):
                tools.add("hand")
                intent = "guided_reach"
            else:
                intent = "find_object"
        return self._plan_result(
            intent,
            tools,
            target_info["target_zh"],
            target_en,
            mode,
            q,
            target_info["target_prompts"],
            target_info.get("target_color", ""),
            target_info.get("target_color_zh", ""),
        )

    def _plan_result(
        self,
        intent: str,
        tools: set[str],
        target_zh: str,
        target_en: str,
        mode: str = "ask",
        question: str = "",
        target_prompts: List[str] | None = None,
        target_color: str = "",
        target_color_zh: str = "",
    ) -> Dict[str, Any]:
        tools = set(self._normalize_tools(list(tools), mode, question))
        plan = {
            "intent": intent,
            "tools": sorted(tools),
            "target_zh": target_zh,
            "target_en": target_en,
            "target_color": target_color,
            "target_color_zh": target_color_zh,
            "target_prompts": target_prompts or self._target_prompts(target_en, target_color),
            "mode": mode,
            "safety_priority": "safety" in tools,
            "planner": "heuristic",
        }
        return self._apply_context_probe(plan, question, mode)

    def _apply_context_probe(self, plan: Dict[str, Any], question: str, mode: str) -> Dict[str, Any]:
        if not self._needs_context_probe(plan, question, mode):
            return plan
        tools = set(plan.get("tools") or [])
        tools.update({"detect", "ocr", "safety", "memory"})
        updated = dict(plan)
        updated["tools"] = sorted(tool for tool in tools if tool in TOOL_SET)
        updated["intent"] = "visual_question"
        updated["context_probe"] = True
        updated["safety_priority"] = True
        return updated

    def _needs_context_probe(self, plan: Dict[str, Any], question: str, mode: str) -> bool:
        if mode != "ask":
            return False
        if not question.strip():
            return False
        intent = str(plan.get("intent") or "")
        if intent in {
            "read_text",
            "find_object",
            "guided_reach",
            "hand_status",
            "safety",
            "memory",
            "spatial_relation",
        }:
            return False
        if str(plan.get("target_zh") or plan.get("target_en") or "").strip():
            return False
        return True

    def _loads_json(self, content: str) -> Dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start : end + 1])
            raise

    def _normalize_tools(self, tools: List[str], mode: str, question: str) -> List[str]:
        normalized = {tool for tool in tools if tool in TOOL_SET}
        if mode == "ocr":
            normalized.add("ocr")
            normalized.add("safety")
            normalized.discard("detect")
            normalized.discard("hand")
        elif mode in {"safety", "auto_safety"}:
            normalized = {"detect", "hand", "safety"}
        elif mode == "memory":
            normalized.add("memory")
            normalized.add("detect")
            normalized.add("hand")
            normalized.add("safety")
        elif mode == "find":
            normalized.add("detect")
            normalized.add("hand")
            normalized.add("safety")
        elif mode == "describe":
            normalized.add("detect")
            normalized.add("hand")
            normalized.add("safety")
        elif mode == "gesture":
            normalized.add("hand")
            normalized.add("safety")
            normalized.discard("detect")
        elif mode in {"reach", "auto_reach"}:
            normalized.add("detect")
            normalized.add("hand")
            normalized.add("safety")
        if any(word in question for word in OCR_WORDS) or self._medicine_ocr_focus(question):
            normalized.add("ocr")
        if any(word in question for word in GESTURE_WORDS):
            normalized.add("hand")
            normalized.add("safety")
        if self._needs_hand_guidance(question):
            normalized.add("detect")
            normalized.add("hand")
            normalized.add("safety")
        if not normalized:
            normalized = {"detect", "safety"}
        return sorted(normalized)

    def _needs_hand_guidance(self, question: str) -> bool:
        return any(word in question for word in HAND_ACTION_WORDS)

    def _asks_medicine_name(self, question: str) -> bool:
        q = question.strip()
        if any(word in q for word in MEDICINE_NAME_WORDS):
            return True
        return "药" in q and any(word in q for word in ["名字", "名称", "叫什么", "什么名", "是什么"])

    def _medicine_ocr_focus(self, question: str) -> str:
        q = question.strip()
        if self._asks_medicine_name(q):
            return "medicine_name"
        if any(word in q for word in MEDICINE_USAGE_WORDS):
            return "medicine_usage"
        if any(word in q for word in MEDICINE_DOSAGE_WORDS):
            return "medicine_dosage"
        if any(word in q for word in MEDICINE_INGREDIENT_WORDS):
            return "medicine_ingredients"
        if "药" in q and any(word in q for word in ["什么", "介绍", "说明", "用途"]):
            return "medicine_usage"
        return ""

    def _parse_spatial_relation(self, question: str) -> Dict[str, Dict[str, Any]]:
        if not any(word in question for word in SPATIAL_RELATION_WORDS):
            return {}
        patterns = [
            r"(?P<subject>[\u4e00-\u9fffA-Za-z0-9 ]{1,16})在(?P<reference>[\u4e00-\u9fffA-Za-z0-9 ]{1,16})的(?:什么)?位置",
            r"(?P<subject>[\u4e00-\u9fffA-Za-z0-9 ]{1,16})相对(?P<reference>[\u4e00-\u9fffA-Za-z0-9 ]{1,16})(?:的)?(?:什么)?位置",
        ]
        for pattern in patterns:
            match = re.search(pattern, question)
            if not match:
                continue
            subject = self._clean_relation_target(match.group("subject"))
            reference = self._clean_relation_target(match.group("reference"))
            subject_info = self._resolve_target(subject)
            reference_info = self._resolve_target(reference)
            if subject_info.get("target_en") and reference_info.get("target_en"):
                return {"subject": subject_info, "reference": reference_info}
        return {}

    def _clean_relation_target(self, text: str) -> str:
        text = text.strip(" ？?，,。的")
        text = re.sub(r"^(请问|帮我看一下|帮我看|帮我找一下|帮我找|那个|这个|一个|一只|一把|一张|一瓶|一盒)", "", text)
        text = re.sub(r"(在哪里|在哪|是什么|是)$", "", text)
        return text.strip(" ？?，,。的")

    def _relation_prompts(self, relation: Dict[str, Dict[str, Any]]) -> List[str]:
        prompts: List[str] = []
        for role in ("subject", "reference"):
            info = relation.get(role) or {}
            target_en = str(info.get("target_en") or "")
            color = str(info.get("target_color") or "")
            aliases = TARGET_PROMPT_ALIASES.get(target_en, [target_en])
            if color and target_en:
                prompts.append(f"{color} {target_en}")
            for alias in aliases[:2]:
                if color:
                    prompts.append(f"{color} {alias}")
                else:
                    prompts.append(alias)
        result: List[str] = []
        for prompt in prompts:
            prompt = prompt.strip()
            if prompt and prompt not in result:
                result.append(prompt)
        return result[:8]

    def _extract_target(self, question: str) -> str:
        for key in sorted(TARGET_MAP, key=len, reverse=True):
            if key in question:
                color_zh, _color = self._extract_color(question)
                if color_zh and color_zh not in key:
                    return f"{color_zh}{key}"
                return key
        match = re.search(r"(找|寻找|找一下|找找|看到|有没有|哪里有|在哪)(?P<target>[\u4e00-\u9fffA-Za-z0-9 ]{1,16})", question)
        if match:
            target = match.group("target").strip(" 了吗？?，,。的在哪里")
            target = re.sub(r"^(一下|一个|一只|一把|一张|一瓶|一盒|我的|这个|那个|附近的|前面的)", "", target)
            target = re.sub(r"(在哪里|在哪|在吗|有没有|吗|呢)$", "", target)
            return target[:16]
        return ""

    def _resolve_target(self, target_zh: str) -> Dict[str, Any]:
        target_zh = target_zh.strip()
        if not target_zh:
            return {"target_zh": "", "target_en": "", "target_prompts": [], "target_color": "", "target_color_zh": ""}
        if target_zh in self._target_cache:
            return self._target_cache[target_zh]

        target_color_zh, target_color = self._extract_color(target_zh)
        object_zh = self._strip_color_words(target_zh)

        target_en = TARGET_MAP.get(object_zh, "") or TARGET_MAP.get(target_zh, "")
        if not target_en:
            for key, value in sorted(TARGET_MAP.items(), key=lambda item: len(item[0]), reverse=True):
                if key in object_zh or object_zh in key or key in target_zh or target_zh in key:
                    target_en = value
                    break

        if not target_en and self.enabled:
            target_en = self._translate_target(target_zh)

        if not target_en:
            target_en = target_zh

        result = {
            "target_zh": target_zh,
            "target_en": target_en,
            "target_color": target_color,
            "target_color_zh": target_color_zh,
            "target_prompts": self._target_prompts(target_en, target_color),
        }
        self._target_cache[target_zh] = result
        return result

    def _extract_color(self, text: str) -> tuple[str, str]:
        for word, (zh, en) in sorted(COLOR_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
            if word in text:
                return zh, en
        return "", ""

    def _strip_color_words(self, text: str) -> str:
        cleaned = text
        for word in sorted(COLOR_WORDS, key=len, reverse=True):
            cleaned = cleaned.replace(word, "")
        cleaned = cleaned.replace("的", "")
        return cleaned.strip() or text.strip()

    def _target_prompts(self, target_en: str, target_color: str = "") -> List[str]:
        target_en = target_en.strip()
        if not target_en:
            return []
        prompts = TARGET_PROMPT_ALIASES.get(target_en, [target_en])
        result: List[str] = []
        if target_color:
            for prompt in prompts:
                prompt = prompt.strip()
                if prompt:
                    result.append(f"{target_color} {prompt}")
        for prompt in prompts:
            prompt = prompt.strip()
            if prompt and prompt not in result:
                result.append(prompt)
        return result[:8]

    def _translate_target(self, target_zh: str) -> str:
        try:
            assert self.client is not None
            response = self.client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Translate a Chinese object name for open-vocabulary object detection. "
                            "Return JSON only: {\"english\": \"short noun phrase\"}. "
                            "Use concrete visual nouns, no adjectives unless essential."
                        ),
                    },
                    {"role": "user", "content": json.dumps({"target_zh": target_zh}, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                max_tokens=80,
            )
            parsed = self._loads_json(response.choices[0].message.content or "{}")
            english = str(parsed.get("english") or "").strip().lower()
            english = re.sub(r"[^a-z0-9 /_-]", "", english).replace("_", " ")
            return english[:40]
        except Exception:
            return ""

    def _safety_answer(self, safety: Dict[str, Any], quality: Dict[str, Any]) -> Dict[str, Any]:
        if not quality.get("usable", True):
            return {
                "action": "reobserve",
                "speech": quality.get("speech") or "画面不够稳定，请先停一下并重新对准。",
                "confidence": 0.55,
                "used_evidence_ids": [],
                "planner": "local_safety",
            }
        if safety.get("risk_level") in {"high", "medium"}:
            return {
                "action": "safety_alert",
                "speech": safety.get("speech") or "前方可能有障碍，请慢一点。",
                "confidence": safety.get("confidence", 0.6),
                "used_evidence_ids": safety.get("evidence_ids", []),
                "planner": "local_safety",
            }
        return {
            "action": "answer",
            "speech": "当前画面中没有检测到明显近处障碍，请仍然慢速前进。",
            "confidence": 0.55,
            "used_evidence_ids": [],
            "planner": "local_safety",
        }

    def _fallback_answer(
        self,
        question: str,
        current_evidence: List[Dict[str, Any]],
        memory: List[Dict[str, Any]],
        quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not quality.get("usable", True):
            return {
                "action": "reobserve",
                "speech": quality.get("speech") or "画面质量不够好，请重新对准后再试。",
                "confidence": 0.5,
                "used_evidence_ids": [],
                "planner": "fallback",
            }
        objects = [e for e in current_evidence if e.get("type") == "object" and not e.get("expired")]
        texts = [e for e in current_evidence if e.get("type") == "text" and not e.get("expired")]
        if texts:
            text = "；".join(str(e.get("text") or e.get("label")) for e in texts[:4])
            return {
                "action": "answer",
                "speech": f"我读到这些文字：{text}",
                "confidence": 0.65,
                "used_evidence_ids": [e.get("id") for e in texts[:4]],
                "planner": "fallback",
            }
        if objects:
            names = "，".join(f"{e.get('position')}有{self._evidence_label(e)}" for e in objects[:5])
            return {
                "action": "answer",
                "speech": f"当前检测到：{names}。这只是视觉检测结果，请谨慎移动。",
                "confidence": 0.6,
                "used_evidence_ids": [e.get("id") for e in objects[:5]],
                "planner": "fallback",
            }
        if memory:
            recent = memory[-1]
            return {
                "action": "answer",
                "speech": f"最近一次记录是{self._evidence_label(recent)}，位置是{recent.get('position')}，但这可能已经过期。",
                "confidence": 0.45,
                "used_evidence_ids": [recent.get("id")],
                "planner": "fallback",
            }
        return {
            "action": "reobserve",
            "speech": "我还没有得到足够稳定的视觉证据，请缓慢移动摄像头重新观察。",
            "confidence": 0.4,
            "used_evidence_ids": [],
            "planner": "fallback",
        }

    def _read_text_answer(
        self,
        plan: Dict[str, Any],
        current_evidence: List[Dict[str, Any]],
        quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not quality.get("usable", True):
            return {
                "action": "reobserve",
                "speech": quality.get("speech") or "画面质量不够好，请重新对准文字后再读。",
                "confidence": 0.5,
                "used_evidence_ids": [],
                "planner": "local_ocr",
            }

        texts = [
            e for e in current_evidence
            if e.get("type") == "text" and not e.get("expired") and (e.get("text") or e.get("label"))
        ]
        if not texts:
            return {
                "action": "reobserve",
                "speech": "我还没有读到清晰文字。请把书名或文字放到画面中间，靠近一点并保持稳定。",
                "confidence": 0.5,
                "used_evidence_ids": [e.get("id") for e in current_evidence if e.get("type") == "tool_status"],
                "planner": "local_ocr",
            }

        focus = str(plan.get("ocr_focus") or "")
        if focus.startswith("medicine_"):
            reading_texts = sorted(texts, key=self._text_reading_order)
            reading_snippets = self._unique_text_snippets(reading_texts[:24])
            medicine_texts = sorted(texts, key=self._medicine_text_score, reverse=True)
            snippets = self._unique_text_snippets(medicine_texts[:16])
            names = self._extract_medicine_names(snippets + reading_snippets)
            if focus == "medicine_usage":
                usage = self._extract_medicine_usage(reading_snippets)
                if usage:
                    name_prefix = f"{names[0]}，" if names else ""
                    speech = f"{name_prefix}主要用于：{usage}。请按说明书或医嘱使用，不要仅凭识别结果用药。"
                    return {
                        "action": "answer",
                        "speech": speech[:300],
                        "confidence": max(0.58, float(medicine_texts[0].get("confidence") or 0.0)),
                        "used_evidence_ids": [e.get("id") for e in reading_texts[:12]],
                        "planner": "local_medicine_ocr",
                    }
                if names:
                    speech = f"我能确认它像是{names[0]}，但还没有稳定读到适应症。请把包装上“适应症”或说明文字对准、靠近一点。"
                    return {
                        "action": "reobserve",
                        "speech": speech[:300],
                        "confidence": 0.5,
                        "used_evidence_ids": [e.get("id") for e in medicine_texts[:8]],
                        "planner": "local_medicine_ocr",
                    }
            if focus == "medicine_dosage":
                dosage = self._extract_medicine_dosage(reading_snippets)
                if dosage:
                    name_prefix = f"{names[0]}，" if names else ""
                    speech = f"{name_prefix}我读到的用法用量是：{dosage}。请以说明书和医嘱为准。"
                    return {
                        "action": "answer",
                        "speech": speech[:300],
                        "confidence": max(0.58, float(medicine_texts[0].get("confidence") or 0.0)),
                        "used_evidence_ids": [e.get("id") for e in reading_texts[:12]],
                        "planner": "local_medicine_ocr",
                    }
            if focus == "medicine_ingredients":
                ingredients = self._extract_medicine_ingredients(reading_snippets)
                if ingredients:
                    name_prefix = f"{names[0]}，" if names else ""
                    speech = f"{name_prefix}我读到的成分或补充内容是：{ingredients}。请再核对包装。"
                    return {
                        "action": "answer",
                        "speech": speech[:300],
                        "confidence": max(0.58, float(medicine_texts[0].get("confidence") or 0.0)),
                        "used_evidence_ids": [e.get("id") for e in reading_texts[:12]],
                        "planner": "local_medicine_ocr",
                    }
            if names:
                speech = "药名可能是：" + "；".join(names[:3]) + "。请再核对包装或请明眼人确认，不要仅凭识别结果用药。"
                return {
                    "action": "answer",
                    "speech": speech[:300],
                    "confidence": max(0.58, float(medicine_texts[0].get("confidence") or 0.0)),
                    "used_evidence_ids": [e.get("id") for e in medicine_texts[:8]],
                    "planner": "local_medicine_ocr",
                }
            speech = "我读到了文字，但还不能稳定提取药品关键信息：" + "，".join(reading_snippets[:5]) + "。请把药盒或药板正面对准、靠近一点再试。"
            return {
                "action": "reobserve",
                "speech": speech[:300],
                "confidence": 0.5,
                "used_evidence_ids": [e.get("id") for e in reading_texts[:8]],
                "planner": "local_medicine_ocr",
            }
        texts = sorted(texts, key=lambda e: float(e.get("confidence") or 0.0), reverse=True)
        snippets = self._unique_text_snippets(texts[:5])
        speech = "我读到：" + "，".join(snippets) + "。"
        return {
            "action": "answer",
            "speech": speech[:300],
            "confidence": max(0.55, float(texts[0].get("confidence") or 0.0)),
            "used_evidence_ids": [e.get("id") for e in texts[:5]],
            "planner": "local_ocr",
        }

    def _unique_text_snippets(self, items: List[Dict[str, Any]]) -> List[str]:
        snippets: List[str] = []
        for item in items:
            text = str(item.get("text") or item.get("label") or "").strip()
            if text and text not in snippets:
                snippets.append(text)
        return snippets

    def _medicine_text_score(self, item: Dict[str, Any]) -> float:
        text = self._clean_ocr_text(str(item.get("text") or item.get("label") or ""))
        score = float(item.get("confidence") or 0.0) * 0.25
        if self._extract_medicine_names([text]):
            score += 4.0
        if any(word in text for word in ["药品名称", "通用名称", "商品名称", "口服", "盐酸", "Oral", "Powder", "Tablets"]):
            score += 1.2
        if any(word in text for word in ["适应症", "预防", "治疗", "引起", "补充", "用法", "用量", "公司", "有限"]):
            score -= 1.4
        bbox = item.get("bbox") or []
        if isinstance(bbox, list) and len(bbox) >= 4:
            width = max(0.0, float(bbox[2]) - float(bbox[0]))
            height = max(0.0, float(bbox[3]) - float(bbox[1]))
            area = width * height
            score += min(1.0, area / 50000.0)
            score += max(0.0, 0.8 - float(bbox[1]) / 720.0)
        return score

    def _text_reading_order(self, item: Dict[str, Any]) -> tuple[float, float, float]:
        bbox = item.get("bbox") or []
        if isinstance(bbox, list) and len(bbox) >= 4:
            return (float(bbox[1]), float(bbox[0]), -float(item.get("confidence") or 0.0))
        return (9999.0, 9999.0, -float(item.get("confidence") or 0.0))

    def _extract_medicine_names(self, snippets: List[str]) -> List[str]:
        candidates: List[str] = []
        for raw in snippets:
            text = self._clean_ocr_text(raw)
            if not text:
                continue
            for form in sorted(MEDICINE_FORM_WORDS, key=len, reverse=True):
                pattern = rf"([\u4e00-\u9fffA-Za-z0-9·（）()]{{2,28}}{re.escape(form)}(?:[（(][ⅠⅡⅢIVX0-9]+[）)])?)"
                for match in re.findall(pattern, text):
                    cleaned = self._clean_medicine_candidate(match)
                    if self._looks_like_medicine_name(cleaned):
                        candidates.append(cleaned)
            for match in re.findall(r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,5}(?:\s+[（(][IVX0-9]+[）)])?)\b", raw):
                if self._looks_like_english_medicine_name(match):
                    candidates.append(match.strip())
            for match in re.findall(r"\b[A-Z][A-Z0-9-]{3,}\b", text):
                if self._looks_like_latin_medicine_name(match):
                    candidates.append(match)
            for match in re.findall(r"([\u4e00-\u9fff]{2,8})[®牌]?", text):
                if self._looks_like_chinese_brand(match):
                    candidates.append(match)

        result: List[str] = []
        for item in candidates:
            if item and item not in result:
                result.append(item)
        return result

    def _extract_medicine_usage(self, snippets: List[str]) -> str:
        clean = [self._clean_ocr_text(item) for item in snippets if self._clean_ocr_text(item)]
        if not clean:
            return ""

        treatment = self._first_snippet(clean, ["预防", "治疗", "用于"])
        dehydration = self._first_snippet(clean, ["脱水"])
        electrolyte = self._first_snippet(clean, ["补充", "钠", "钾", "氯"])
        english = self._first_snippet(clean, ["Prevention", "treatment", "dehydration", "diarrhea"])

        parts: List[str] = []
        if treatment and dehydration and dehydration != treatment:
            if "腹泻" in treatment and "引起" in dehydration:
                parts.append(treatment + dehydration)
            else:
                parts.extend([treatment, dehydration])
        elif treatment:
            parts.append(treatment)
        elif dehydration:
            parts.append(dehydration)
        if electrolyte and electrolyte not in parts:
            parts.append(electrolyte)
        if not parts and english:
            parts.append(english)
        return "；".join(self._dedupe_text(parts))[:220]

    def _extract_medicine_dosage(self, snippets: List[str]) -> str:
        clean = [self._clean_ocr_text(item) for item in snippets if self._clean_ocr_text(item)]
        candidates = [
            item for item in clean
            if any(word in item for word in ["用法", "用量", "一次", "每日", "每天", "口服", "冲", "温开水", "ml", "mL", "毫升"])
        ]
        return "；".join(self._dedupe_text(candidates[:4]))[:220]

    def _extract_medicine_ingredients(self, snippets: List[str]) -> str:
        clean = [self._clean_ocr_text(item) for item in snippets if self._clean_ocr_text(item)]
        candidates = [
            item for item in clean
            if any(word in item for word in ["成分", "含", "补充", "钠", "钾", "氯", "葡萄糖", "sodium", "potassium", "chloride"])
        ]
        return "；".join(self._dedupe_text(candidates[:5]))[:220]

    def _first_snippet(self, snippets: List[str], words: List[str]) -> str:
        lowered_words = [word.lower() for word in words]
        for item in snippets:
            lower = item.lower()
            if any(word in item or word in lower for word in lowered_words):
                return item
        return ""

    def _dedupe_text(self, items: List[str]) -> List[str]:
        result: List[str] = []
        for item in items:
            item = item.strip(" ，,。；;")
            if item and item not in result:
                result.append(item)
        return result

    def _clean_ocr_text(self, text: str) -> str:
        return (
            text.strip()
            .replace(" ", "")
            .replace("　", "")
            .replace("：", ":")
            .replace("（", "(")
            .replace("）", ")")
        )

    def _clean_medicine_candidate(self, text: str) -> str:
        if isinstance(text, tuple):
            text = "".join(str(part or "") for part in text)
        text = text.strip(" ,，。:：;；|/\\[]【】{}")
        text = re.sub(r"^(药品名称|通用名称|商品名称|名称|品名|药名)[:：]?", "", text)
        text = re.sub(r"^(每片含|含|规格|批准文号|国药准字|生产企业).*$", "", text)
        return text.strip(" ,，。:：;；")

    def _looks_like_medicine_name(self, text: str) -> bool:
        if len(text) < 2 or len(text) > 32:
            return False
        if any(bad in text for bad in ["公司", "有限", "批号", "生产", "批准", "国药准字", "用法", "用量"]):
            return False
        return any(form in text for form in MEDICINE_FORM_WORDS) or any(prefix in text for prefix in ["盐酸", "硫酸", "马来酸", "阿莫", "头孢"])

    def _looks_like_latin_medicine_name(self, text: str) -> bool:
        if len(text) < 4 or len(text) > 20:
            return False
        if text in MEDICINE_LATIN_BLACKLIST:
            return False
        digits = sum(ch.isdigit() for ch in text)
        if digits > max(1, len(text) // 3):
            return False
        return True

    def _looks_like_english_medicine_name(self, text: str) -> bool:
        normalized = text.lower()
        if len(text) < 8 or len(text) > 70:
            return False
        dosage_words = ["tablet", "tablets", "powder", "capsule", "capsules", "solution", "salts", "oral"]
        bad_words = ["company", "limited", "pharmaceutical", "prevention", "treatment", "caused", "diarrhea"]
        if any(word in normalized for word in bad_words):
            return False
        return any(word in normalized for word in dosage_words)

    def _looks_like_chinese_brand(self, text: str) -> bool:
        if len(text) < 2 or len(text) > 8:
            return False
        if any(bad in text for bad in ["公司", "有限", "药业", "制药", "包装", "说明", "生产", "批准", "盐酸", "每片"]):
            return False
        return any(hint in text for hint in ["爽", "泰", "康", "宁", "力", "乐", "舒", "林", "敏", "安"])

    def _spatial_relation_answer(
        self,
        plan: Dict[str, Any],
        current_evidence: List[Dict[str, Any]],
        quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not quality.get("usable", True):
            return {
                "action": "reobserve",
                "speech": quality.get("speech") or "画面质量不够好，请重新对准后再判断相对位置。",
                "confidence": 0.5,
                "used_evidence_ids": [],
                "planner": "local_relation",
            }

        relation = plan.get("relation") or {}
        subject_info = relation.get("subject") or {}
        reference_info = relation.get("reference") or {}
        subject_name = str(subject_info.get("target_zh") or "目标")
        reference_name = str(reference_info.get("target_zh") or "参照物")
        objects = [e for e in current_evidence if e.get("type") == "object" and not e.get("expired")]
        subject_candidates = [
            item for item in objects if self._object_matches_relation_target(subject_info, item)
        ]
        reference_candidates = [
            item for item in objects if self._object_matches_relation_target(reference_info, item)
        ]

        if not subject_candidates or not reference_candidates:
            missing = []
            if not subject_candidates:
                missing.append(subject_name)
            if not reference_candidates:
                missing.append(reference_name)
            seen = "，".join(f"{e.get('position')}有{self._evidence_label(e)}" for e in objects[:4])
            suffix = f"当前看到：{seen}。" if seen else ""
            return {
                "action": "reobserve",
                "speech": f"我还没稳定确认{'和'.join(missing)}。{suffix}请保持画面稳定，再稍微靠近两个罐子。",
                "confidence": 0.45,
                "used_evidence_ids": [e.get("id") for e in objects[:4]],
                "planner": "local_relation",
            }

        subject = max(subject_candidates, key=lambda item: self._relation_match_score(subject_info, item))
        reference = max(reference_candidates, key=lambda item: self._relation_match_score(reference_info, item))
        sx, sy = self._bbox_center(subject.get("bbox"))
        rx, ry = self._bbox_center(reference.get("bbox"))
        frame_w, frame_h = self._frame_size(subject, reference)
        dx = sx - rx
        dy = sy - ry

        horizontal = ""
        vertical = ""
        if abs(dx) > frame_w * 0.08:
            horizontal = "右侧" if dx > 0 else "左侧"
        if abs(dy) > frame_h * 0.10:
            vertical = "下方" if dy > 0 else "上方"
        if horizontal and vertical:
            relation_text = f"{horizontal}偏{vertical}"
        elif horizontal:
            relation_text = horizontal
        elif vertical:
            relation_text = vertical
        else:
            relation_text = "附近，几乎在同一位置"

        return {
            "action": "answer",
            "speech": f"{subject_name}在{reference_name}的{relation_text}。",
            "confidence": 0.68,
            "used_evidence_ids": [subject.get("id"), reference.get("id")],
            "planner": "local_relation",
        }

    def _object_matches_relation_target(self, info: Dict[str, Any], item: Dict[str, Any]) -> bool:
        label = str(item.get("label") or "").lower()
        attrs = item.get("attributes") or {}
        if attrs.get("duplicate_of") or attrs.get("target_rejected_by"):
            return False
        target_en = str(info.get("target_en") or "").lower()
        target_color = str(info.get("target_color") or "").lower()
        target_color_zh = str(info.get("target_color_zh") or "")
        label_zh = self._evidence_label(item)

        aliases = TARGET_CLASS_ALIASES.get(target_en, {target_en}) if target_en else set()
        label_object_match = bool(target_en and (label in aliases or target_en in label or any(alias in label for alias in aliases)))
        if not label_object_match and target_en == "can":
            label_object_match = "can" in label or "罐" in label_zh or label in {"cup"}
        if not label_object_match:
            return False

        if not target_color:
            return True
        if target_color in label or (target_color_zh and target_color_zh in label_zh):
            return True
        scores = attrs.get("color_scores") or {}
        target_score = float(scores.get(target_color) or attrs.get("color_score") or 0.0)
        competing = max(
            [float(value or 0.0) for key, value in scores.items() if key != target_color and key in {"red", "green", "blue", "yellow"}],
            default=0.0,
        )
        return target_score >= 0.14 and target_score >= competing * 1.25

    def _relation_match_score(self, info: Dict[str, Any], item: Dict[str, Any]) -> float:
        attrs = item.get("attributes") or {}
        color = str(info.get("target_color") or "")
        scores = attrs.get("color_scores") or {}
        color_score = float(scores.get(color) or attrs.get("color_score") or 0.0) if color else 0.0
        return float(item.get("confidence") or 0.0) + color_score * 0.35

    def _hand_status_answer(
        self,
        current_evidence: List[Dict[str, Any]],
        quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not quality.get("usable", True):
            return {
                "action": "reobserve",
                "speech": quality.get("speech") or "画面质量不够好，请把手放到画面中央并保持一下。",
                "confidence": 0.5,
                "used_evidence_ids": [],
                "planner": "local_hand_status",
            }

        hands = [e for e in current_evidence if e.get("type") == "hand" and not e.get("expired")]
        hand_status = [e for e in current_evidence if e.get("label") == "hand_tracker_unavailable"]
        if not hands:
            if hand_status:
                return {
                    "action": "reobserve",
                    "speech": "手部跟踪还没启用或加载失败，我现在只能看到普通物体，不能判断手势。",
                    "confidence": 0.4,
                    "used_evidence_ids": [hand_status[0].get("id")],
                    "planner": "local_hand_status",
                }
            return {
                "action": "reobserve",
                "speech": "我还没有看到手。请把手放到画面中央，手掌朝向摄像头，停半秒。",
                "confidence": 0.45,
                "used_evidence_ids": [],
                "planner": "local_hand_status",
            }

        parts = []
        for hand in hands[:2]:
            attrs = hand.get("attributes") or {}
            label = self._evidence_label(hand)
            gesture = str(attrs.get("gesture_zh") or "手势不清")
            motion = attrs.get("motion") or {}
            motion_zh = str(motion.get("label_zh") or "")
            position = str(hand.get("position") or "")
            if motion_zh:
                parts.append(f"{position}有{label}，{gesture}，{motion_zh}")
            else:
                parts.append(f"{position}有{label}，{gesture}")
        return {
            "action": "answer",
            "speech": "；".join(parts) + "。",
            "confidence": max(0.55, max(float(hand.get("confidence") or 0.0) for hand in hands)),
            "used_evidence_ids": [hand.get("id") for hand in hands[:2]],
            "planner": "local_hand_status",
        }

    def _guided_reach_answer(
        self,
        plan: Dict[str, Any],
        current_evidence: List[Dict[str, Any]],
        quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not quality.get("usable", True):
            return {
                "action": "reobserve",
                "speech": quality.get("speech") or "画面质量不够好，请先停住并重新对准桌面。",
                "confidence": 0.5,
                "used_evidence_ids": [],
                "planner": "local_guided_reach",
            }

        objects = [e for e in current_evidence if e.get("type") == "object" and not e.get("expired")]
        hands = [e for e in current_evidence if e.get("type") == "hand" and not e.get("expired")]
        hand_status = [e for e in current_evidence if e.get("label") == "hand_tracker_unavailable"]
        targets = self._target_matches(plan, objects)
        target_name = str(plan.get("target_zh") or plan.get("target_en") or "目标物体")
        continuous = str(plan.get("mode") or "") in {"auto_reach", "auto_assist"}

        if not targets:
            weak_targets = self._weak_target_candidates(plan, objects)
            if weak_targets:
                best = max(
                    weak_targets,
                    key=lambda e: float(e.get("confidence") or 0.0)
                    + float((e.get("attributes") or {}).get("color_score") or 0.0),
                )
                speech = (
                    f"疑似{target_name}，先对准它。"
                    if continuous
                    else f"我看到疑似{target_name}，在{best.get('position')}。请先把摄像头对准它，确认后我再引导手去拿。"
                )
                return {
                    "action": "answer",
                    "speech": speech,
                    "confidence": max(0.42, min(0.62, float(best.get("confidence") or 0.0))),
                    "used_evidence_ids": [best.get("id")],
                    "planner": "local_guided_reach_weak",
                }
            seen = "，".join(f"{e.get('position')}有{self._evidence_label(e)}" for e in objects[:3])
            suffix = f"当前看到：{seen}。" if seen else ""
            speech = (
                f"还没确认{target_name}，请稍微移动相机。"
                if continuous
                else f"我还没稳定确认{target_name}。{suffix}请把目标放到画面中间再慢慢靠近。"
            )
            return {
                "action": "reobserve",
                "speech": speech,
                "confidence": 0.45,
                "used_evidence_ids": [e.get("id") for e in objects[:3]],
                "planner": "local_guided_reach",
            }

        target = max(targets, key=lambda e: float(e.get("confidence") or 0.0))
        if not hands:
            if hand_status:
                return {
                    "action": "reobserve",
                    "speech": "我已经看到目标，但手部跟踪还没启用。需要安装 MediaPipe 后，我才能引导手去拿。",
                    "confidence": 0.45,
                    "used_evidence_ids": [target.get("id"), hand_status[0].get("id")],
                    "planner": "local_guided_reach",
                }
            return {
                "action": "reobserve",
                "speech": (
                    f"看到了{target_name}，请把手伸进画面。"
                    if continuous
                    else f"看到了{target_name}，在{target.get('position')}。请把手从画面下方慢慢伸进来，我会继续指方向。"
                ),
                "confidence": max(0.55, float(target.get("confidence") or 0.0)),
                "used_evidence_ids": [target.get("id")],
                "planner": "local_guided_reach",
            }

        target_center = self._bbox_center(target.get("bbox"))
        hand = min(hands, key=lambda item: self._point_distance(self._hand_point(item), target_center))
        hand_point = self._hand_point(hand)
        frame_w, frame_h = self._frame_size(target, hand)
        target_bbox = target.get("bbox") or []
        hand_bbox = hand.get("bbox") or []
        dx = target_center[0] - hand_point[0]
        dy = target_center[1] - hand_point[1]
        hand_attrs = hand.get("attributes") or {}
        gesture_label = str(hand_attrs.get("gesture") or "")
        gesture = str(hand_attrs.get("gesture_zh") or "")
        motion = hand_attrs.get("motion") or {}
        motion_label = str(motion.get("label") or "")
        motion_zh = str(motion.get("label_zh") or "")
        touch_ratio = self._bbox_touch_ratio(target_bbox, hand_bbox)
        fingertip_touching = self._point_in_bbox(hand_point, target_bbox)
        thumb_tip = hand_attrs.get("thumb_tip")
        thumb_touching = isinstance(thumb_tip, list) and len(thumb_tip) >= 2 and self._point_in_bbox((float(thumb_tip[0]), float(thumb_tip[1])), target_bbox)
        contact = touch_ratio >= 0.08 or fingertip_touching or thumb_touching
        x_close = abs(dx) <= frame_w * 0.08 or contact
        y_close = abs(dy) <= frame_h * 0.10 or contact
        hand_state = f"当前手势是{gesture}" if gesture else "我看到手了"
        if motion_zh:
            hand_state += f"，{motion_zh}"
        agent_state = plan.get("agent") or {}
        agent_phase = str(agent_state.get("phase") or plan.get("agent_phase") or "")
        relation = agent_state.get("hand_target") or {}
        relation_moves = [str(item) for item in relation.get("move_zh", []) if str(item)]

        if continuous and agent_phase in {"align_hand", "approach_target", "prepare_grasp", "close_fingers", "hold", "lift"}:
            if relation.get("moving_away") and relation_moves:
                speech = "方向反了，" + "、".join(relation_moves) + "。"
                confidence = 0.68
            elif agent_phase == "align_hand":
                move_text = "、".join(relation_moves) if relation_moves else self._move_text(dx, dy, x_close, y_close)
                speech = f"{move_text}，慢一点。" if move_text else "保持方向，慢慢靠近。"
                confidence = 0.68
            elif agent_phase == "approach_target":
                speech = "方向对了，继续靠近。"
                confidence = 0.7
            elif agent_phase == "prepare_grasp":
                speech = "很近了，张开手，慢慢靠近。"
                confidence = 0.72
            elif agent_phase == "close_fingers":
                speech = "碰到了，收拢手指。"
                confidence = 0.76
            elif agent_phase == "hold":
                speech = "握住，向上抬。"
                confidence = 0.78
            else:
                speech = "继续向上抬。"
                confidence = 0.8
            return {
                "action": "answer",
                "speech": speech,
                "confidence": confidence,
                "used_evidence_ids": [target.get("id"), hand.get("id")],
                "planner": "local_guided_reach",
            }

        if not (x_close and y_close):
            moves = []
            if not x_close:
                moves.append("向右" if dx > 0 else "向左")
            if not y_close:
                moves.append("向下" if dy > 0 else "向上")
            move_text = "、".join(moves)
            speech = f"{move_text}，慢一点。" if continuous else f"看到了{target_name}，{hand_state}，还没对准。请把手{move_text}慢慢移动一点。"
            confidence = 0.65
        elif gesture_label in {"fist", "pinch"}:
            if motion_label == "moving_up":
                speech = "继续向上抬。" if continuous else f"很好，像是已经抓住{target_name}了。继续慢慢向上抬，动作小一点。"
                confidence = 0.76
            else:
                speech = "握住，向上抬。" if continuous else f"手已经到{target_name}上，{hand_state}。保持收拢，慢慢向上抬一点。"
                confidence = 0.74
        elif contact:
            speech = "碰到了，收拢手指。" if continuous else f"手已经碰到{target_name}附近，{hand_state}。现在收拢手指，轻轻夹住或握住它。"
            confidence = 0.74
        elif gesture_label in {"open_palm", "half_open", "pointing", "unknown"}:
            speech = "方向对了，继续靠近。" if continuous else f"方向对了，手已经接近{target_name}，{hand_state}。手掌稍微张开，继续向前靠近一点。"
            confidence = 0.7
        else:
            speech = "继续向前，碰到后收拢。" if continuous else f"手已经接近{target_name}，{hand_state}。慢慢向前伸，碰到物体后收拢手指。"
            confidence = 0.7

        return {
            "action": "answer",
            "speech": speech,
            "confidence": confidence,
            "used_evidence_ids": [target.get("id"), hand.get("id")],
            "planner": "local_guided_reach",
        }

    def _move_text(self, dx: float, dy: float, x_close: bool, y_close: bool) -> str:
        moves = []
        if not x_close:
            moves.append("向右" if dx > 0 else "向左")
        if not y_close:
            moves.append("向下" if dy > 0 else "向上")
        return "、".join(moves)

    def _find_answer(
        self,
        plan: Dict[str, Any],
        current_evidence: List[Dict[str, Any]],
        quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not quality.get("usable", True):
            return {
                "action": "reobserve",
                "speech": quality.get("speech") or "画面质量不够好，请重新对准后再找。",
                "confidence": 0.5,
                "used_evidence_ids": [],
                "planner": "local_find",
            }

        target_zh = str(plan.get("target_zh") or "").strip()
        target_en = str(plan.get("target_en") or "").strip()
        target_name = target_zh or target_en or "目标物体"
        objects = [e for e in current_evidence if e.get("type") == "object" and not e.get("expired")]

        matches = self._target_matches(plan, objects)

        if matches:
            best = max(matches, key=lambda e: float(e.get("confidence") or 0.0))
            return {
                "action": "answer",
                "speech": f"找到了，{best.get('position')}有{self._evidence_label(best)}。",
                "confidence": max(0.55, float(best.get("confidence") or 0.0)),
                "used_evidence_ids": [best.get("id")],
                "planner": "local_find",
            }

        weak_matches = self._weak_target_candidates(plan, objects)
        if weak_matches:
            best = max(
                weak_matches,
                key=lambda e: float(e.get("confidence") or 0.0)
                + float((e.get("attributes") or {}).get("color_score") or 0.0),
            )
            return {
                "action": "answer",
                "speech": f"我看到疑似{target_name}，在{best.get('position')}。请把摄像头稍微对准它，我会继续确认。",
                "confidence": max(0.42, min(0.62, float(best.get("confidence") or 0.0))),
                "used_evidence_ids": [best.get("id")],
                "planner": "local_find_weak",
            }

        if objects:
            seen = "，".join(f"{e.get('position')}有{self._evidence_label(e)}" for e in objects[:4])
            return {
                "action": "reobserve",
                "speech": f"我还没找到{target_name}。当前看到：{seen}。请缓慢扫一下左右两侧。",
                "confidence": 0.45,
                "used_evidence_ids": [e.get("id") for e in objects[:4]],
                "planner": "local_find",
            }

        return {
            "action": "reobserve",
            "speech": f"我还没找到{target_name}，请把摄像头慢慢转向桌面或手边区域。",
            "confidence": 0.4,
            "used_evidence_ids": [],
            "planner": "local_find",
        }

    def _target_matches(self, plan: Dict[str, Any], objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        target_zh = str(plan.get("target_zh") or "").strip()
        target_en = str(plan.get("target_en") or "").strip()
        target_color = str(plan.get("target_color") or "").strip()
        if not target_color and target_zh:
            _color_zh, target_color = self._extract_color(target_zh)
        matches = []
        for item in objects:
            label = str(item.get("label") or "")
            label_key = label.strip().lower()
            label_zh = self._evidence_label(item)
            attrs = item.get("attributes") or {}
            if attrs.get("target_match"):
                matches.append(item)
                continue
            if (
                attrs.get("target_rejected_by")
                or attrs.get("requires_open_vocab_confirmation")
                or attrs.get("target_color_mismatch")
                or attrs.get("duplicate_of")
            ):
                continue
            if (
                target_en == "can"
                and target_color
                and self._strip_label_color(label_key, target_color) in {"cup", "mug", "drinking cup", "tumbler", "jar"}
                and float(attrs.get("color_score") or 0.0) >= 0.12
            ):
                attrs["target_match"] = True
                attrs["container_surrogate_match"] = True
                if target_zh:
                    attrs["label_zh"] = target_zh
                item["attributes"] = attrs
                matches.append(item)
                continue
            if target_color or target_en in {"can", "cup"}:
                continue
            aliases = TARGET_CLASS_ALIASES.get(target_en, {target_en}) if target_en else set()
            if target_en and label in aliases:
                matches.append(item)
            elif target_zh and (target_zh in label_zh or label_zh in target_zh):
                matches.append(item)
        return matches

    def _weak_target_candidates(self, plan: Dict[str, Any], objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        target_zh = str(plan.get("target_zh") or "").strip()
        target_en = str(plan.get("target_en") or "").strip()
        target_color = str(plan.get("target_color") or "").strip()
        if not target_color and target_zh:
            _color_zh, target_color = self._extract_color(target_zh)
        if target_en != "can" or not target_color:
            return []
        weak_labels = {"box", "carton", "red box", "red carton", "bottle", "red bottle"}
        candidates = []
        for item in objects:
            if item.get("type") != "object" or item.get("expired"):
                continue
            attrs = item.get("attributes") or {}
            label_key = str(item.get("label") or "").strip().lower()
            color_score = float(attrs.get("color_score") or 0.0)
            confidence = float(item.get("confidence") or 0.0)
            if attrs.get("weak_target_match"):
                pass
            elif self._strip_label_color(label_key, target_color) not in weak_labels and label_key not in weak_labels:
                continue
            if not attrs.get("weak_target_match") and (color_score < 0.32 or confidence < 0.10):
                continue
            attrs["weak_target_match"] = True
            if target_zh:
                attrs["label_zh"] = f"疑似{target_zh}"
            item["attributes"] = attrs
            candidates.append(item)
        return candidates

    def _strip_label_color(self, label: str, color: str) -> str:
        label = label.strip().lower()
        color = color.strip().lower()
        prefix = f"{color} "
        return label[len(prefix) :] if color and label.startswith(prefix) else label

    def _bbox_center(self, bbox: Any) -> tuple[float, float]:
        if isinstance(bbox, list) and len(bbox) >= 4:
            return (float(bbox[0] + bbox[2]) / 2.0, float(bbox[1] + bbox[3]) / 2.0)
        return (0.0, 0.0)

    def _hand_point(self, hand: Dict[str, Any]) -> tuple[float, float]:
        attrs = hand.get("attributes") or {}
        point = attrs.get("index_tip") or attrs.get("palm_center")
        if isinstance(point, list) and len(point) >= 2:
            return (float(point[0]), float(point[1]))
        return self._bbox_center(hand.get("bbox"))

    def _frame_size(self, target: Dict[str, Any], hand: Dict[str, Any]) -> tuple[float, float]:
        for item in (hand, target):
            attrs = item.get("attributes") or {}
            frame_size = attrs.get("frame_size")
            if isinstance(frame_size, list) and len(frame_size) >= 2:
                return (max(1.0, float(frame_size[0])), max(1.0, float(frame_size[1])))
        bbox = target.get("bbox") or hand.get("bbox") or [0, 0, 1280, 720]
        return (max(1.0, float(max(bbox[0], bbox[2], 1280))), max(1.0, float(max(bbox[1], bbox[3], 720))))

    def _point_distance(self, left: tuple[float, float], right: tuple[float, float]) -> float:
        return ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5

    def _point_in_bbox(self, point: tuple[float, float], bbox: Any) -> bool:
        if not isinstance(bbox, list) or len(bbox) < 4:
            return False
        return float(bbox[0]) <= point[0] <= float(bbox[2]) and float(bbox[1]) <= point[1] <= float(bbox[3])

    def _bbox_touch_ratio(self, target_bbox: Any, hand_bbox: Any) -> float:
        if not isinstance(target_bbox, list) or not isinstance(hand_bbox, list):
            return 0.0
        if len(target_bbox) < 4 or len(hand_bbox) < 4:
            return 0.0
        tx1, ty1, tx2, ty2 = [float(v) for v in target_bbox[:4]]
        hx1, hy1, hx2, hy2 = [float(v) for v in hand_bbox[:4]]
        ix1, iy1 = max(tx1, hx1), max(ty1, hy1)
        ix2, iy2 = min(tx2, hx2), min(ty2, hy2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        if inter <= 0.0:
            return 0.0
        target_area = max(1.0, (tx2 - tx1) * (ty2 - ty1))
        hand_area = max(1.0, (hx2 - hx1) * (hy2 - hy1))
        return inter / min(target_area, hand_area)

    def _memory_answer(self, memory: List[Dict[str, Any]]) -> Dict[str, Any]:
        usable = []
        seen_keys = set()
        for item in reversed(memory):
            if item.get("type") not in {"object", "text"}:
                continue
            label = self._evidence_label(item)
            position = str(item.get("position") or "未知位置")
            key = (label, position)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            usable.append(item)
            if len(usable) >= 6:
                break

        if not usable:
            return {
                "action": "reobserve",
                "speech": "我还没有形成可用的短时记忆，请先观察一次场景。",
                "confidence": 0.4,
                "used_evidence_ids": [],
                "planner": "local_memory",
            }

        parts = []
        for item in usable:
            age = float(item.get("age") or 0.0)
            label = self._evidence_label(item)
            position = item.get("position") or "未知位置"
            if item.get("type") == "text":
                parts.append(f"{round(age)}秒前读到“{label}”")
            else:
                parts.append(f"{round(age)}秒前{position}有{label}")
        return {
            "action": "answer",
            "speech": "最近记到：" + "；".join(parts) + "。这些记录可能已经变化，请以当前画面为准。",
            "confidence": 0.5,
            "used_evidence_ids": [item.get("id") for item in usable],
            "planner": "local_memory",
        }

    def _evidence_label(self, item: Dict[str, Any]) -> str:
        attrs = item.get("attributes") or {}
        return str(attrs.get("label_zh") or item.get("text") or item.get("label") or "目标")
