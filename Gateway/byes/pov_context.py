from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


_ALLOWED_MODES = {"decisions_only", "decisions_plus_highlights", "full"}


def build_context_pack(pov_ir: dict[str, Any], budget: dict[str, Any], mode: str) -> dict[str, Any]:
    if not isinstance(pov_ir, dict):
        raise ValueError("pov_ir must be object")

    selected_mode = _normalize_mode(mode)
    max_chars = _as_non_negative_int((budget or {}).get("maxChars"), 2000)
    max_tokens_approx = _as_non_negative_int((budget or {}).get("maxTokensApprox"), 500)

    decisions_in = _normalize_decisions(pov_ir.get("decisionPoints"))
    highlights_in = _normalize_text_rows(pov_ir.get("highlights"))
    tokens_in = _normalize_text_rows(pov_ir.get("tokens"), truncate_to=120 if selected_mode == "full" else None)
    events_in = _as_dict_list(pov_ir.get("events"))

    in_decision_chars = sum(len(_decision_snippet(row)) for row in decisions_in)
    in_highlights_chars = sum(len(str(row.get("text", ""))) for row in highlights_in)
    in_token_chars = sum(len(str(row.get("text", ""))) for row in tokens_in)

    selected_decisions: list[dict[str, Any]] = []
    selected_highlights: list[dict[str, Any]] = []
    selected_tokens: list[dict[str, Any]] = []
    included_chars = 0

    for row in decisions_in:
        snippet = _decision_snippet(row)
        if _fits_budget(included_chars, len(snippet), max_chars, max_tokens_approx):
            selected_decisions.append(row)
            included_chars += len(snippet)

    if selected_mode in {"decisions_plus_highlights", "full"}:
        for row in highlights_in:
            snippet = _highlight_snippet(row)
            if _fits_budget(included_chars, len(snippet), max_chars, max_tokens_approx):
                selected_highlights.append(row)
                included_chars += len(snippet)

    if selected_mode == "full":
        for row in tokens_in:
            snippet = _token_snippet(row)
            if _fits_budget(included_chars, len(snippet), max_chars, max_tokens_approx):
                selected_tokens.append(row)
                included_chars += len(snippet)

    chars_total = included_chars
    token_approx = _token_approx(chars_total)

    dropped_decisions = max(0, len(decisions_in) - len(selected_decisions))
    dropped_highlights = max(0, len(highlights_in) - len(selected_highlights))
    dropped_tokens = max(0, len(tokens_in) - len(selected_tokens))

    in_total_chars = in_decision_chars
    if selected_mode in {"decisions_plus_highlights", "full"}:
        in_total_chars += in_highlights_chars
    if selected_mode == "full":
        in_total_chars += in_token_chars
    chars_dropped = max(0, in_total_chars - chars_total)

    run_id = str(pov_ir.get("runId", "")).strip() or "pov-context"
    pack: dict[str, Any] = {
        "schemaVersion": "pov.context.v1",
        "runId": run_id,
        "generatedAtMs": 0,
        "budget": {
            "maxChars": max_chars,
            "maxTokensApprox": max_tokens_approx,
            "mode": selected_mode,
        },
        "stats": {
            "in": {
                "decisions": len(decisions_in),
                "events": len(events_in),
                "highlights": len(highlights_in),
                "tokens": len(tokens_in),
                "tokenChars": in_token_chars,
                "highlightsChars": in_highlights_chars,
            },
            "out": {
                "decisions": len(selected_decisions),
                "highlights": len(selected_highlights),
                "tokens": len(selected_tokens),
                "charsTotal": chars_total,
                "tokenApprox": token_approx,
            },
            "truncation": {
                "decisionsDropped": dropped_decisions,
                "highlightsDropped": dropped_highlights,
                "tokensDropped": dropped_tokens,
                "charsDropped": chars_dropped,
            },
        },
        "content": {
            "decisions": selected_decisions,
            "highlights": selected_highlights,
            "tokens": selected_tokens,
        },
    }
    return pack


def render_context_text(context_pack: dict[str, Any]) -> dict[str, str]:
    if not isinstance(context_pack, dict):
        raise ValueError("context_pack must be object")

    budget = context_pack.get("budget", {})
    budget = budget if isinstance(budget, dict) else {}
    max_chars = _as_non_negative_int(budget.get("maxChars"), 2000)
    mode = _normalize_mode(str(budget.get("mode", "decisions_plus_highlights")))
    content = context_pack.get("content", {})
    content = content if isinstance(content, dict) else {}

    decisions = _as_dict_list(content.get("decisions"))
    highlights = _as_dict_list(content.get("highlights"))
    tokens = _as_dict_list(content.get("tokens"))

    lines: list[str] = []
    lines.append(f"RunId: {str(context_pack.get('runId', '')).strip() or 'unknown'}")
    lines.append(f"Mode: {mode}")
    lines.append(f"Budget: maxChars={max_chars}, maxTokensApprox={_as_non_negative_int(budget.get('maxTokensApprox'), 500)}")
    lines.append("")
    lines.append("Decisions:")
    if decisions:
        for row in decisions:
            lines.append(f"- {_decision_snippet(row)}")
    else:
        lines.append("- (none)")

    if mode in {"decisions_plus_highlights", "full"}:
        lines.append("")
        lines.append("Highlights:")
        if highlights:
            for row in highlights:
                lines.append(f"- {_highlight_snippet(row)}")
        else:
            lines.append("- (none)")

    if mode == "full":
        lines.append("")
        lines.append("Tokens:")
        if tokens:
            for row in tokens:
                lines.append(f"- {_token_snippet(row)}")
        else:
            lines.append("- (none)")

    prompt = "\n".join(lines).strip()
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars]

    summary = "out(decisions={d}, highlights={h}, tokens={t}, tokenApprox={ta})".format(
        d=int(context_pack.get("stats", {}).get("out", {}).get("decisions", 0) or 0),
        h=int(context_pack.get("stats", {}).get("out", {}).get("highlights", 0) or 0),
        t=int(context_pack.get("stats", {}).get("out", {}).get("tokens", 0) or 0),
        ta=int(context_pack.get("stats", {}).get("out", {}).get("tokenApprox", 0) or 0),
    )
    return {"prompt": prompt, "summary": summary}


def finalize_context_pack_text(context_pack: dict[str, Any], text_payload: dict[str, Any], generated_at_ms: int) -> dict[str, Any]:
    pack = deepcopy(context_pack)
    text = text_payload if isinstance(text_payload, dict) else {}
    prompt = str(text.get("prompt", ""))
    summary = str(text.get("summary", "")).strip()
    if summary:
        pack["text"] = {"prompt": prompt, "summary": summary}
    else:
        pack["text"] = {"prompt": prompt}

    stats = pack.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    out = stats.get("out")
    out = out if isinstance(out, dict) else {}
    out["charsTotal"] = len(prompt)
    out["tokenApprox"] = _token_approx(len(prompt))
    stats["out"] = out
    pack["stats"] = stats
    pack["generatedAtMs"] = int(max(0, generated_at_ms))
    return pack


def _normalize_mode(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in _ALLOWED_MODES:
        return "decisions_plus_highlights"
    return text


def _normalize_decisions(raw: Any) -> list[dict[str, Any]]:
    rows = _as_dict_list(raw)
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        item = {
            "id": str(row.get("id", "")).strip() or "decision",
            "t0Ms": _as_non_negative_int(row.get("t0Ms"), 0),
            "t1Ms": _as_non_negative_int(row.get("t1Ms"), _as_non_negative_int(row.get("t0Ms"), 0)),
            "state": str(row.get("state", "")).strip(),
            "action": str(row.get("action", "")).strip(),
            "outcome": str(row.get("outcome", "")).strip(),
        }
        confidence = _as_float(row.get("confidence"))
        if confidence is not None:
            item["confidence"] = confidence
        constraints = row.get("constraints")
        if isinstance(constraints, list):
            item["constraints"] = [str(x) for x in constraints if str(x).strip()]
        alternatives = row.get("alternatives")
        if isinstance(alternatives, list):
            item["alternatives"] = [str(x) for x in alternatives if str(x).strip()]
        cleaned.append(item)
    cleaned.sort(key=lambda x: (int(x.get("t0Ms", 0)), str(x.get("id", ""))))
    return cleaned


def _normalize_text_rows(raw: Any, *, truncate_to: int | None = None) -> list[dict[str, Any]]:
    rows = _as_dict_list(raw)
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        t_ms = _as_non_negative_int(row.get("tMs"), _as_non_negative_int(row.get("tsMs"), 0))
        text = _extract_text(row)
        if truncate_to is not None and len(text) > int(truncate_to):
            text = text[: int(truncate_to)]
        cleaned.append({"tMs": t_ms, "text": text})
    cleaned.sort(key=lambda x: (int(x.get("tMs", 0)), str(x.get("text", ""))))
    return cleaned


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _extract_text(row: dict[str, Any]) -> str:
    for key in ("text", "summary", "content"):
        value = row.get(key)
        if isinstance(value, str):
            return value
    return ""


def _decision_snippet(row: dict[str, Any]) -> str:
    parts = [
        f"id={str(row.get('id', '')).strip()}",
        f"t={int(row.get('t0Ms', 0) or 0)}-{int(row.get('t1Ms', 0) or 0)}",
        f"state={str(row.get('state', '')).strip()}",
        f"action={str(row.get('action', '')).strip()}",
        f"outcome={str(row.get('outcome', '')).strip()}",
    ]
    confidence = row.get("confidence")
    if isinstance(confidence, (int, float)):
        parts.append(f"confidence={float(confidence):.3f}")
    return "; ".join(parts)


def _highlight_snippet(row: dict[str, Any]) -> str:
    return f"tMs={int(row.get('tMs', 0) or 0)}; text={str(row.get('text', ''))}"


def _token_snippet(row: dict[str, Any]) -> str:
    return f"tMs={int(row.get('tMs', 0) or 0)}; text={str(row.get('text', ''))}"


def _token_approx(chars: int) -> int:
    if chars <= 0:
        return 0
    return int(math.ceil(float(chars) / 4.0))


def _fits_budget(current_chars: int, item_chars: int, max_chars: int, max_tokens_approx: int) -> bool:
    next_chars = int(current_chars) + int(item_chars)
    if next_chars > int(max_chars):
        return False
    return _token_approx(next_chars) <= int(max_tokens_approx)


def _as_non_negative_int(value: Any, default: int) -> int:
    try:
        if value is None or isinstance(value, bool):
            return int(default)
        out = int(float(value))
        if out < 0:
            return int(default)
        return out
    except Exception:
        return int(default)


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None
