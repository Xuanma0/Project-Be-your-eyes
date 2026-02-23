from __future__ import annotations

import re
from typing import Any


_SEG_STOPWORDS = {
    "seg",
    "top",
    "objects",
    "object",
    "bbox",
    "mode",
    "score",
    "targets",
    "textchars",
    "prompt",
    "summary",
    "and",
    "the",
    "with",
    "for",
    "from",
}

_POV_STOPWORDS = {
    "pov",
    "context",
    "summary",
    "prompt",
    "decision",
    "decisions",
    "state",
    "action",
    "outcome",
    "frame",
    "frames",
    "risk",
    "high",
    "medium",
    "low",
    "critical",
    "with",
    "that",
    "this",
    "from",
    "into",
    "then",
    "when",
    "will",
    "have",
}

_TOKEN_RE = re.compile(r"\b[a-zA-Z_]+\b")
_SEG_CALL_TOKEN_RE = re.compile(r"([a-zA-Z_]+)\(")
_SLAM_STATE_RE = re.compile(r"state\s*=\s*(tracking|lost|relocalized|unknown)")
_MAX_SEG_MATCHED = 5
_MAX_POV_HITS = 20
_MAX_SLAM_MATCHED = 5


def compute_plan_context_alignment(
    plan_request: dict[str, Any] | None,
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    request_payload = plan_request if isinstance(plan_request, dict) else {}
    plan_payload = plan if isinstance(plan, dict) else {}
    contexts = request_payload.get("contexts")
    contexts = contexts if isinstance(contexts, dict) else {}

    seg_ctx = contexts.get("seg")
    seg_ctx = seg_ctx if isinstance(seg_ctx, dict) else {}
    pov_ctx = contexts.get("pov")
    pov_ctx = pov_ctx if isinstance(pov_ctx, dict) else {}
    slam_ctx = contexts.get("slam")
    slam_ctx = slam_ctx if isinstance(slam_ctx, dict) else {}

    seg_fragment = str(seg_ctx.get("promptFragment", "")).strip()
    pov_fragment = str(pov_ctx.get("promptFragment", "")).strip()
    slam_fragment = str(slam_ctx.get("promptFragment", "")).strip()

    seg_present = bool(seg_ctx.get("included")) and bool(seg_fragment)
    pov_present = bool(pov_ctx.get("included")) and bool(pov_fragment)
    slam_present = bool(slam_ctx.get("present")) and bool(slam_fragment)

    plan_text = _collect_plan_text(plan_payload)
    if not plan_text:
        plan_text = _collect_plan_debug_text(plan_payload)
    plan_tokens = _extract_tokens(plan_text, min_len=3, stopwords=set())

    seg_labels = _extract_seg_labels(seg_fragment) if seg_present else set()
    seg_matched = sorted(label for label in seg_labels if label in plan_tokens)[:_MAX_SEG_MATCHED]
    seg_hit = len(seg_matched) > 0
    seg_coverage = _safe_ratio(len(seg_matched), len(seg_labels))

    pov_tokens = _extract_tokens(pov_fragment, min_len=4, stopwords=_POV_STOPWORDS) if pov_present else set()
    pov_hits_all = sorted(token for token in pov_tokens if token in plan_tokens)
    pov_hits = pov_hits_all[:_MAX_POV_HITS]
    pov_hit_count = len(pov_hits)
    pov_hit = pov_hit_count > 0
    pov_coverage = _safe_ratio(pov_hit_count, len(pov_tokens))

    slam_state = _extract_slam_state(slam_fragment) if slam_present else None
    slam_keywords = _extract_slam_keywords(slam_fragment) if slam_present else set()
    slam_matched: list[str] = []
    if slam_present:
        for token in sorted(slam_keywords):
            if token in plan_tokens:
                slam_matched.append(token)
        if slam_state and slam_state in plan_tokens and slam_state not in slam_matched:
            slam_matched.insert(0, slam_state)
        slam_matched = slam_matched[:_MAX_SLAM_MATCHED]
    slam_hit = bool(slam_matched)
    slam_coverage = 1.0 if slam_hit else 0.0

    meta_payload = plan_payload.get("meta")
    meta_payload = meta_payload if isinstance(meta_payload, dict) else {}
    context_used_detail = meta_payload.get("contextUsedDetail")
    context_used_detail = context_used_detail if isinstance(context_used_detail, dict) else {}
    if not context_used_detail:
        planner_meta = meta_payload.get("planner")
        planner_meta = planner_meta if isinstance(planner_meta, dict) else {}
        planner_detail = planner_meta.get("contextUsedDetail")
        if isinstance(planner_detail, dict):
            context_used_detail = planner_detail
    slam_used_override = context_used_detail.get("slam")
    seg_used = bool(seg_hit)
    pov_used = bool(pov_hit)
    slam_used = bool(slam_used_override) if isinstance(slam_used_override, bool) else bool(slam_present and slam_hit)
    context_used = bool(seg_used or pov_used or slam_used)

    return {
        "schemaVersion": "plan.context_alignment.v1",
        "seg": {
            "present": bool(seg_present),
            "labelCount": int(len(seg_labels)),
            "hit": bool(seg_hit),
            "coverage": float(round(seg_coverage, 6)),
            "matched": seg_matched,
            "planTextChars": int(len(plan_text)),
        },
        "pov": {
            "present": bool(pov_present),
            "tokenCount": int(len(pov_tokens)),
            "hit": bool(pov_hit),
            "coverage": float(round(pov_coverage, 6)),
            "hitCount": int(pov_hit_count),
        },
        "slam": {
            "present": bool(slam_present),
            "hit": bool(slam_hit),
            "coverage": float(round(slam_coverage, 6)),
            "planTextChars": int(len(plan_text)),
            "matched": slam_matched,
        },
        "contextUsed": context_used,
        "contextUsedDetail": {
            "seg": seg_used,
            "pov": pov_used,
            "slam": slam_used,
        },
    }


def _extract_seg_labels(fragment: str) -> set[str]:
    if not fragment:
        return set()
    labels: set[str] = set()
    for token in _SEG_CALL_TOKEN_RE.findall(fragment):
        normalized = _normalize_token(token)
        if normalized and normalized not in _SEG_STOPWORDS and len(normalized) >= 3:
            labels.add(normalized)
    for token in _TOKEN_RE.findall(fragment):
        normalized = _normalize_token(token)
        if normalized and normalized not in _SEG_STOPWORDS and len(normalized) >= 3:
            labels.add(normalized)
    return labels


def _extract_tokens(text: str, *, min_len: int, stopwords: set[str]) -> set[str]:
    if not text:
        return set()
    tokens: set[str] = set()
    for token in _TOKEN_RE.findall(text):
        normalized = _normalize_token(token)
        if not normalized:
            continue
        if len(normalized) < max(1, int(min_len)):
            continue
        if normalized in stopwords:
            continue
        tokens.add(normalized)
    return tokens


def _collect_plan_text(plan_payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    intent = plan_payload.get("intent")
    if isinstance(intent, str) and intent.strip():
        chunks.append(intent.strip())
    actions = plan_payload.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            for key in ("type", "reason"):
                value = action.get(key)
                if isinstance(value, str) and value.strip():
                    chunks.append(value.strip())
            payload = action.get("payload")
            _collect_strings(payload, chunks)
    return " ".join(chunks).strip().lower()


def _collect_plan_debug_text(plan_payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    meta = plan_payload.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    for source in (meta, meta.get("planner") if isinstance(meta.get("planner"), dict) else {}):
        if not isinstance(source, dict):
            continue
        debug_text = source.get("debugText")
        if isinstance(debug_text, str) and debug_text.strip():
            chunks.append(debug_text.strip())
    return " ".join(chunks).strip().lower()


def _collect_strings(value: Any, output: list[str]) -> None:
    if isinstance(value, str):
        text = value.strip()
        if text:
            output.append(text)
        return
    if isinstance(value, list):
        for item in value:
            _collect_strings(item, output)
        return
    if isinstance(value, dict):
        for key in sorted(value.keys()):
            _collect_strings(value.get(key), output)


def _normalize_token(token: str) -> str:
    normalized = str(token or "").strip().lower()
    normalized = normalized.strip("_")
    return normalized


def _extract_slam_state(fragment: str) -> str | None:
    if not fragment:
        return None
    match = _SLAM_STATE_RE.search(fragment.lower())
    if not match:
        return None
    return _normalize_token(match.group(1))


def _extract_slam_keywords(fragment: str) -> set[str]:
    if not fragment:
        return set()
    keywords = _extract_tokens(fragment, min_len=3, stopwords=set())
    lower_fragment = fragment.lower()
    for token in ("tracking", "lost", "relocalized", "relocaliz"):
        if token in lower_fragment:
            keywords.add(token)
    return keywords


def _safe_ratio(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return float(num) / float(den)
