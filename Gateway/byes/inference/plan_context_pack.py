from __future__ import annotations

import math
import os
from typing import Any


_ALLOWED_MODES = {
    "seg_plus_pov_plus_risk",
    "seg_plus_pov",
    "pov_plus_risk",
    "seg_only",
    "pov_only",
    "risk_only",
}

DEFAULT_PLAN_CONTEXT_PACK_BUDGET = {
    "maxChars": 2000,
    "mode": "seg_plus_pov_plus_risk",
}


def resolve_plan_context_pack_budget_from_env() -> dict[str, Any]:
    max_chars = _to_nonnegative_int(
        os.getenv("BYES_PLAN_CTX_MAX_CHARS"),
        int(DEFAULT_PLAN_CONTEXT_PACK_BUDGET["maxChars"]),
    )
    mode_raw = str(os.getenv("BYES_PLAN_CTX_MODE", DEFAULT_PLAN_CONTEXT_PACK_BUDGET["mode"])).strip().lower()
    mode = mode_raw if mode_raw in _ALLOWED_MODES else str(DEFAULT_PLAN_CONTEXT_PACK_BUDGET["mode"])
    return {"maxChars": int(max_chars), "mode": mode}


def build_plan_context_pack(
    *,
    run_id: str,
    seg_context: dict[str, Any] | None,
    pov_context: dict[str, Any] | None,
    risk_context: dict[str, Any] | None,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_budget = _normalize_budget(budget)
    mode = str(normalized_budget["mode"])
    max_chars = int(normalized_budget["maxChars"])

    risk_fragment, risk_part = _build_risk_fragment(risk_context)
    pov_fragment, pov_part = _build_pov_fragment(pov_context)
    seg_fragment, seg_part = _build_seg_fragment(seg_context)

    include_risk = mode in {"seg_plus_pov_plus_risk", "pov_plus_risk", "risk_only"}
    include_pov = mode in {"seg_plus_pov_plus_risk", "seg_plus_pov", "pov_plus_risk", "pov_only"}
    include_seg = mode in {"seg_plus_pov_plus_risk", "seg_plus_pov", "seg_only"}

    ordered_parts = [
        ("risk", risk_fragment if include_risk else ""),
        ("pov", pov_fragment if include_pov else ""),
        ("seg", seg_fragment if include_seg else ""),
    ]
    raw_lengths = {name: len(text) for name, text in ordered_parts}

    kept_by_name: dict[str, str] = {"risk": "", "pov": "", "seg": ""}
    remaining = max(0, int(max_chars))
    for name, text in ordered_parts:
        if not text or remaining <= 0:
            kept_by_name[name] = ""
            continue
        keep_len = min(len(text), remaining)
        kept_by_name[name] = text[:keep_len]
        remaining -= keep_len

    lines = [kept_by_name["risk"], kept_by_name["pov"], kept_by_name["seg"]]
    prompt = "\n".join([line for line in lines if line]).strip()
    chars_total = len(prompt)
    token_approx = _token_approx(chars_total)

    risk_chars = len(kept_by_name["risk"])
    pov_chars = len(kept_by_name["pov"])
    seg_chars = len(kept_by_name["seg"])
    risk_chars_dropped = max(0, raw_lengths["risk"] - risk_chars)
    pov_chars_dropped = max(0, raw_lengths["pov"] - pov_chars)
    seg_chars_dropped = max(0, raw_lengths["seg"] - seg_chars)
    chars_dropped = risk_chars_dropped + pov_chars_dropped + seg_chars_dropped

    summary = (
        f"mode={mode}; chars={chars_total}/{max_chars}; "
        f"parts(risk/pov/seg)={risk_chars}/{pov_chars}/{seg_chars}; dropped={chars_dropped}"
    )

    return {
        "schemaVersion": "plan.context_pack.v1",
        "runId": str(run_id or "").strip() or "plan-context-pack",
        "budget": {
            "maxChars": int(max_chars),
            "mode": mode,
        },
        "parts": {
            "seg": seg_part if include_seg else None,
            "pov": pov_part if include_pov else None,
            "risk": risk_part if include_risk else None,
        },
        "stats": {
            "out": {
                "charsTotal": int(chars_total),
                "tokenApprox": int(token_approx),
                "segChars": int(seg_chars),
                "povChars": int(pov_chars),
                "riskChars": int(risk_chars),
            },
            "truncation": {
                "charsDropped": int(chars_dropped),
                "segCharsDropped": int(seg_chars_dropped),
                "povCharsDropped": int(pov_chars_dropped),
                "riskCharsDropped": int(risk_chars_dropped),
            },
        },
        "text": {
            "summary": summary,
            "prompt": prompt,
        },
    }


def _normalize_budget(raw: dict[str, Any] | None) -> dict[str, Any]:
    env_budget = resolve_plan_context_pack_budget_from_env()
    source = raw if isinstance(raw, dict) else {}
    max_chars = _to_nonnegative_int(source.get("maxChars"), int(env_budget["maxChars"]))
    mode_raw = str(source.get("mode", env_budget["mode"])).strip().lower()
    mode = mode_raw if mode_raw in _ALLOWED_MODES else str(env_budget["mode"])
    return {"maxChars": int(max_chars), "mode": mode}


def _build_seg_fragment(seg_context: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
    payload = seg_context if isinstance(seg_context, dict) else {}
    text = payload.get("text")
    text = text if isinstance(text, dict) else {}
    fragment = str(text.get("promptFragment", "")).strip()
    summary = str(text.get("summary", "")).strip()
    stats = payload.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    out = stats.get("out")
    out = out if isinstance(out, dict) else {}
    trunc = stats.get("truncation")
    trunc = trunc if isinstance(trunc, dict) else {}
    part = {
        "present": bool(fragment),
        "promptFragment": fragment or None,
        "summary": summary or None,
        "segments": _to_nonnegative_int(out.get("segments"), 0),
        "chars": len(fragment),
        "segmentsDropped": _to_nonnegative_int(trunc.get("segmentsDropped"), 0),
    }
    return fragment, part


def _build_pov_fragment(pov_context: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
    payload = pov_context if isinstance(pov_context, dict) else {}
    text = payload.get("text")
    text = text if isinstance(text, dict) else {}
    fragment = str(text.get("prompt", "")).strip()
    if not fragment:
        fragment = str(text.get("summary", "")).strip()
    summary = str(text.get("summary", "")).strip()
    stats = payload.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    out = stats.get("out")
    out = out if isinstance(out, dict) else {}
    trunc = stats.get("truncation")
    trunc = trunc if isinstance(trunc, dict) else {}
    part = {
        "present": bool(fragment),
        "promptFragment": fragment or None,
        "summary": summary or None,
        "chars": len(fragment),
        "tokenApprox": _to_nonnegative_int(out.get("tokenApprox"), 0),
        "charsDropped": _to_nonnegative_int(trunc.get("charsDropped"), 0),
    }
    return fragment, part


def _build_risk_fragment(risk_context: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
    payload = risk_context if isinstance(risk_context, dict) else {}
    risk_level = str(payload.get("riskLevel", "")).strip().lower() or "low"
    hazards_count = _to_nonnegative_int(payload.get("hazardsCount"), 0)
    hazards_top = payload.get("hazardsTop")
    hazards_top = hazards_top if isinstance(hazards_top, list) else []
    hazard_items: list[str] = []
    for row in hazards_top[:3]:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("hazardKind", "")).strip() or "unknown"
        severity = str(row.get("severity", "")).strip().lower() or "warning"
        hazard_items.append(f"{kind}:{severity}")
    hazards_text = ", ".join(hazard_items) if hazard_items else "none"
    fragment = f"[RISK] level={risk_level} hazards={hazards_count} top={hazards_text}"
    part = {
        "present": True,
        "riskLevel": risk_level,
        "hazardsCount": int(hazards_count),
        "hazardsTop": hazard_items,
        "chars": len(fragment),
    }
    return fragment, part


def _to_nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return int(default)
        return max(0, int(float(value)))
    except Exception:
        return int(default)


def _token_approx(chars_total: int) -> int:
    if int(chars_total) <= 0:
        return 0
    return int(math.ceil(float(chars_total) / 4.0))
