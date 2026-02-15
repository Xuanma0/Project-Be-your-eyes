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
_MAX_SEG_MATCHED = 5
_MAX_POV_HITS = 20


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

    seg_fragment = str(seg_ctx.get("promptFragment", "")).strip()
    pov_fragment = str(pov_ctx.get("promptFragment", "")).strip()

    seg_present = bool(seg_ctx.get("included")) and bool(seg_fragment)
    pov_present = bool(pov_ctx.get("included")) and bool(pov_fragment)

    plan_text = _collect_plan_text(plan_payload)
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
        "contextUsed": bool(seg_hit or pov_hit),
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


def _safe_ratio(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return float(num) / float(den)
