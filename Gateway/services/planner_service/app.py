from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, request

try:
    from .validate_action_plan import validate_and_normalize
    from .pov_adapter import parse_pov_ir, parse_pov_ir_obj, pov_to_action_plan
except ImportError:  # pragma: no cover - supports running as script
    from validate_action_plan import validate_and_normalize
    from pov_adapter import parse_pov_ir, parse_pov_ir_obj, pov_to_action_plan

app = Flask(__name__)

_ALLOWED_RISK = {"low", "medium", "high", "critical"}
_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_DEFAULT_ENDPOINT = "http://127.0.0.1:19211/plan"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_prompt_template(name: str) -> str:
    path = _PROMPTS_DIR / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _render_prompts(req: dict[str, Any], prompt_version: str) -> tuple[str, str]:
    system_tpl = _load_prompt_template("planner_system.md")
    user_tpl = _load_prompt_template("planner_user.md")

    context_pack = req.get("contextPack")
    context_pack = context_pack if isinstance(context_pack, dict) else {}
    context_text = context_pack.get("text")
    context_text = context_text if isinstance(context_text, dict) else {}
    prompt_text = str(context_text.get("prompt", "")).strip()
    seg_context = req.get("segContext")
    seg_context = seg_context if isinstance(seg_context, dict) else {}
    seg_context_text = seg_context.get("text")
    seg_context_text = seg_context_text if isinstance(seg_context_text, dict) else {}
    seg_context_fragment = str(seg_context_text.get("promptFragment", "")).strip()
    if str(prompt_version).strip().lower() == "v2" and seg_context_fragment:
        if prompt_text:
            prompt_text = f"{prompt_text}\n\n{seg_context_fragment}"
        else:
            prompt_text = seg_context_fragment

    risk_summary = req.get("riskSummary")
    risk_summary = risk_summary if isinstance(risk_summary, dict) else {}
    constraints = req.get("constraints")
    constraints = constraints if isinstance(constraints, dict) else {}

    user_body = user_tpl
    user_body = user_body.replace("{{PROMPT_VERSION}}", prompt_version)
    user_body = user_body.replace("{{RUN_ID}}", str(req.get("runId", "")))
    user_body = user_body.replace("{{FRAME_SEQ}}", str(req.get("frameSeq", "")))
    user_body = user_body.replace("{{CONTEXT_PROMPT}}", prompt_text)
    user_body = user_body.replace("{{RISK_SUMMARY_JSON}}", json.dumps(risk_summary, ensure_ascii=False, indent=2))
    user_body = user_body.replace("{{CONSTRAINTS_JSON}}", json.dumps(constraints, ensure_ascii=False, indent=2))

    system_body = system_tpl.replace("{{PROMPT_VERSION}}", prompt_version)
    return system_body, user_body


def _normalize_hazards(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    out: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "hazardKind": str(item.get("hazardKind", "")).strip(),
                "severity": str(item.get("severity", "warning")).strip().lower() or "warning",
                "score": item.get("score"),
            }
        )
    return out


def _infer_risk_level(hazards: list[dict[str, Any]]) -> str:
    if any(str(item.get("severity", "")).strip().lower() == "critical" for item in hazards):
        return "critical"
    if any(str(item.get("severity", "")).strip().lower() in {"high", "severe"} for item in hazards):
        return "high"
    if any(str(item.get("severity", "")).strip().lower() in {"warning", "warn", "medium"} for item in hazards):
        return "medium"
    return "low"


def _trim_actions(actions: list[dict[str, Any]], max_actions: int) -> list[dict[str, Any]]:
    ordered = sorted(actions, key=lambda row: _priority_value(row))
    return ordered[: max(1, int(max_actions))]


def _priority_value(action: dict[str, Any]) -> int:
    parsed = _safe_int(action.get("priority"))
    if parsed is None:
        return 9999
    return parsed


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _reference_plan(req: dict[str, Any], endpoint: str) -> dict[str, Any]:
    run_id = str(req.get("runId", "")).strip() or "planner-run"
    frame_seq_raw = req.get("frameSeq")
    frame_seq = int(frame_seq_raw) if isinstance(frame_seq_raw, int) else None

    risk_summary = req.get("riskSummary")
    risk_summary = risk_summary if isinstance(risk_summary, dict) else {}
    hazards = _normalize_hazards(risk_summary.get("hazardsTop"))
    risk_level = _infer_risk_level(hazards)
    if risk_level not in _ALLOWED_RISK:
        risk_level = "low"

    constraints = req.get("constraints")
    constraints = constraints if isinstance(constraints, dict) else {}
    max_actions = int(constraints.get("maxActions", 3) or 3)

    actions: list[dict[str, Any]] = []
    if risk_level == "critical":
        actions.append(
            {
                "type": "confirm",
                "priority": 0,
                "payload": {
                    "text": "High risk ahead. Stop?",
                    "confirmId": f"confirm-{run_id}-{frame_seq or 1}",
                    "timeoutMs": 3000,
                },
                "requiresConfirm": False,
                "blocking": True,
            }
        )
        actions.append(
            {
                "type": "speak",
                "priority": 1,
                "payload": {"text": "High risk zone detected."},
                "requiresConfirm": False,
                "blocking": False,
            }
        )
    elif risk_level in {"medium", "high"}:
        actions.append(
            {
                "type": "speak",
                "priority": 0,
                "payload": {"text": "Caution. Potential hazards ahead."},
                "requiresConfirm": False,
                "blocking": False,
            }
        )
        actions.append(
            {
                "type": "overlay",
                "priority": 1,
                "payload": {"label": "CAUTION", "text": "Potential hazard region"},
                "requiresConfirm": False,
                "blocking": False,
            }
        )
    else:
        actions.append(
            {
                "type": "speak",
                "priority": 0,
                "payload": {"text": "Path looks clear."},
                "requiresConfirm": False,
                "blocking": False,
            }
        )

    actions = _trim_actions(actions, max_actions=max_actions)
    budget = req.get("contextBudget")
    budget = budget if isinstance(budget, dict) else {}

    return {
        "schemaVersion": "byes.action_plan.v1",
        "runId": run_id,
        "frameSeq": frame_seq,
        "generatedAtMs": _now_ms(),
        "intent": "assist_navigation",
        "riskLevel": risk_level,
        "ttlMs": 2000,
        "actions": actions,
        "meta": {
            "planner": {
                "backend": "http",
                "model": "reference-planner-v1",
                "endpoint": endpoint,
            },
            "budget": {
                "contextMaxTokensApprox": int(budget.get("maxTokensApprox", 0) or 0),
                "contextMaxChars": int(budget.get("maxChars", 0) or 0),
                "mode": str(budget.get("mode", "decisions_plus_highlights")),
            },
            "safety": {"guardrailsApplied": []},
        },
    }


def _parse_llm_plan_payload(raw_payload: Any) -> dict[str, Any]:
    if isinstance(raw_payload, dict) and str(raw_payload.get("schemaVersion", "")).strip() == "byes.action_plan.v1":
        return raw_payload
    if isinstance(raw_payload, dict) and isinstance(raw_payload.get("text"), str):
        text = str(raw_payload.get("text", "")).strip()
        if not text:
            raise ValueError("llm_text_empty")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("llm_text_not_object")
        return parsed
    if isinstance(raw_payload, str):
        parsed = json.loads(raw_payload)
        if not isinstance(parsed, dict):
            raise ValueError("llm_str_not_object")
        return parsed
    raise ValueError("llm_payload_unrecognized")


def _call_llm_provider(req: dict[str, Any], endpoint: str, timeout_ms: int, prompt_version: str) -> tuple[dict[str, Any], dict[str, Any]]:
    system_prompt, user_prompt = _render_prompts(req, prompt_version)
    mode = str(os.getenv("BYES_PLANNER_LLM_MODE", "generic")).strip().lower() or "generic"

    if mode == "openai":
        api_key = str(os.getenv("BYES_PLANNER_LLM_API_KEY", "")).strip()
        if not api_key:
            raise RuntimeError("openai_api_key_missing")
        model = str(os.getenv("BYES_PLANNER_LLM_MODEL", "gpt-4o-mini")).strip() or "gpt-4o-mini"
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        response = requests.post(
            endpoint,
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=max(0.2, float(timeout_ms) / 1000.0),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("openai_response_not_object")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("openai_choices_missing")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        parsed = _parse_llm_plan_payload({"text": content} if isinstance(content, str) else content)
        return parsed, {"model": model}

    body = {
        "schemaVersion": "byes.planner.prompt.v1",
        "promptVersion": prompt_version,
        "system": system_prompt,
        "user": user_prompt,
        "constraints": req.get("constraints", {}),
    }
    response = requests.post(
        endpoint,
        json=body,
        timeout=max(0.2, float(timeout_ms) / 1000.0),
    )
    response.raise_for_status()
    payload = response.json()
    parsed = _parse_llm_plan_payload(payload)
    llm_model = ""
    if isinstance(parsed.get("meta"), dict):
        llm_model = str(parsed.get("meta", {}).get("planner", {}).get("model", "")).strip()
    if not llm_model:
        llm_model = str(os.getenv("BYES_PLANNER_LLM_MODEL", "generic-llm-planner-v1")).strip() or "generic-llm-planner-v1"
    return parsed, {"model": llm_model}


def _with_planner_meta(
    plan: dict[str, Any],
    *,
    endpoint: str | None,
    planner_backend: str,
    provider: str,
    prompt_version: str,
    fallback_used: bool,
    fallback_reason: str | None,
    json_valid: bool,
    planner_model: str,
) -> dict[str, Any]:
    out = dict(plan)
    meta = out.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    planner = meta.get("planner")
    planner = planner if isinstance(planner, dict) else {}
    planner["backend"] = planner_backend
    planner["model"] = str(planner_model or planner.get("model", "reference-planner-v1") or "reference-planner-v1")
    planner["endpoint"] = endpoint
    planner["plannerProvider"] = provider
    planner["promptVersion"] = prompt_version
    planner["fallbackUsed"] = bool(fallback_used)
    planner["fallbackReason"] = str(fallback_reason or "") if fallback_reason else None
    planner["jsonValid"] = bool(json_valid)
    meta["planner"] = planner
    out["meta"] = meta
    return out


@app.get("/healthz")
def healthz() -> Any:
    return jsonify({"ok": True, "service": "reference-planner-v1"})


@app.post("/plan")
def plan() -> Any:
    req_payload = request.get_json(silent=True)
    if not isinstance(req_payload, dict):
        return jsonify({"ok": False, "error": "request body must be object"}), 400
    if str(req_payload.get("schemaVersion", "")).strip() != "byes.planner_request.v1":
        return jsonify({"ok": False, "error": "schemaVersion must be byes.planner_request.v1"}), 400

    endpoint = request.headers.get("X-Endpoint") or os.getenv("PLANNER_SERVICE_ENDPOINT", _DEFAULT_ENDPOINT)
    provider_from_body = str(req_payload.get("provider", "")).strip().lower()
    provider = provider_from_body if provider_from_body in {"reference", "llm", "pov"} else str(
        os.getenv("BYES_PLANNER_PROVIDER", "reference")
    ).strip().lower() or "reference"
    prompt_version = str(os.getenv("BYES_PLANNER_PROMPT_VERSION", "v1")).strip() or "v1"
    timeout_ms = int(os.getenv("BYES_PLANNER_LLM_TIMEOUT_MS", "2500") or "2500")
    constraints = req_payload.get("constraints")
    constraints = constraints if isinstance(constraints, dict) else {}

    fallback_used = False
    fallback_reason: str | None = None
    json_valid = True
    planner_model = "reference-planner-v1"
    planner_backend = "http"
    planner_endpoint: str | None = endpoint
    planner_prompt_version = prompt_version

    candidate_plan: dict[str, Any] | None = None
    if provider == "pov":
        planner_prompt_version = "n/a"
        inline_pov = req_payload.get("povIr")
        run_package_path = str(req_payload.get("runPackagePath", "")).strip()
        if isinstance(inline_pov, dict):
            pov_source = "inline"
        elif run_package_path:
            pov_source = "run_package_path"
        else:
            pov_source = "missing"
        if pov_source == "missing":
            fallback_used = True
            fallback_reason = "missing_pov_ir"
            json_valid = False
        else:
            try:
                if pov_source == "inline":
                    pov_ir = parse_pov_ir_obj(inline_pov)
                else:
                    pov_ir = parse_pov_ir(Path(run_package_path) / "pov" / "pov_ir_v1.json")
                run_id = str(req_payload.get("runId", "")).strip() or str(pov_ir.get("runId", "")).strip() or "pov-run"
                frame_seq = req_payload.get("frameSeq") if isinstance(req_payload.get("frameSeq"), int) else None
                pov_plan, _diagnostics = pov_to_action_plan(
                    pov_ir,
                    constraints,
                    run_id=run_id,
                    frame_seq=frame_seq,
                    generated_at_ms=_now_ms(),
                )
                validated_pov_plan, diagnostics = validate_and_normalize(pov_plan, constraints)
                json_valid = bool(diagnostics.get("jsonValid"))
                if validated_pov_plan is None:
                    fallback_used = True
                    fallback_reason = "schema_error"
                    json_valid = False
                else:
                    candidate_plan = validated_pov_plan
                    planner_model = "pov-ir-v1"
                    planner_backend = "pov"
                    planner_endpoint = None
            except FileNotFoundError:
                fallback_used = True
                fallback_reason = "missing_pov_ir"
                json_valid = False
            except Exception:
                fallback_used = True
                fallback_reason = "pov_adapter_error"
                json_valid = False
    elif provider == "llm":
        llm_endpoint = str(os.getenv("BYES_PLANNER_LLM_ENDPOINT", "")).strip()
        if not llm_endpoint:
            fallback_used = True
            fallback_reason = "llm_endpoint_missing"
            json_valid = False
        else:
            try:
                llm_plan, llm_meta = _call_llm_provider(req_payload, llm_endpoint, timeout_ms, prompt_version)
                validated_llm_plan, diagnostics = validate_and_normalize(llm_plan, constraints)
                json_valid = bool(diagnostics.get("jsonValid"))
                if validated_llm_plan is None:
                    fallback_used = True
                    fallback_reason = "schema_error"
                    json_valid = False
                else:
                    candidate_plan = validated_llm_plan
                    planner_model = str(llm_meta.get("model", "generic-llm-planner-v1") or "generic-llm-planner-v1")
            except requests.Timeout:
                fallback_used = True
                fallback_reason = "timeout"
                json_valid = False
            except requests.RequestException:
                fallback_used = True
                fallback_reason = "http_error"
                json_valid = False
            except json.JSONDecodeError:
                fallback_used = True
                fallback_reason = "invalid_json"
                json_valid = False
            except ValueError:
                fallback_used = True
                fallback_reason = "invalid_json"
                json_valid = False
            except Exception:
                fallback_used = True
                fallback_reason = "schema_error"
                json_valid = False

    if candidate_plan is None:
        reference = _reference_plan(req_payload, endpoint)
        candidate_plan, diagnostics = validate_and_normalize(reference, constraints)
        if candidate_plan is None:
            return jsonify({"ok": False, "error": "reference_planner_invalid", "diagnostics": diagnostics}), 500
        planner_model = "reference-planner-v1"
        planner_backend = "http"
        planner_endpoint = endpoint

    final = _with_planner_meta(
        candidate_plan,
        endpoint=planner_endpoint,
        planner_backend=planner_backend,
        provider=provider,
        prompt_version=planner_prompt_version,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        json_valid=json_valid,
        planner_model=planner_model,
    )
    return jsonify(final)


if __name__ == "__main__":
    host = os.getenv("PLANNER_SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("PLANNER_SERVICE_PORT", "19211"))
    app.run(host=host, port=port)
