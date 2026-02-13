from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = "byes.event.v1"

_FRAME_RE = re.compile(r"(?:frame[_-]?|seq[_-]?)(\d+)", re.IGNORECASE)
_NUM_RE = re.compile(r"(\d+)")


def normalize_event(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    if not isinstance(raw, dict):
        return None, ["raw_not_object"]

    event = raw.get("event") if isinstance(raw.get("event"), dict) else raw
    if not isinstance(event, dict):
        return None, ["event_not_object"]

    if str(event.get("schemaVersion", "")).strip() == SCHEMA_VERSION:
        normalized, warn = _normalize_v1_passthrough(raw, event)
        warnings.extend(warn)
        return normalized, warnings

    normalized = _normalize_legacy(raw, event, warnings)
    if normalized is None:
        if not warnings:
            warnings.append("normalize_failed")
        return None, warnings
    return normalized, warnings


def iter_normalized_ws_events(path: Path) -> Iterator[dict[str, Any]]:
    summary = collect_normalized_ws_events(path)
    for item in summary["events"]:
        yield item


def collect_normalized_ws_events(path: Path) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    dropped = 0

    with path.open("r", encoding="utf-8-sig") as fp:
        for line_no, raw_line in enumerate(fp, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                dropped += 1
                warnings.append(f"line_{line_no}:json_parse_failed")
                continue
            if not isinstance(obj, dict):
                dropped += 1
                warnings.append(f"line_{line_no}:not_object")
                continue
            normalized, warns = normalize_event(obj)
            warnings.extend([f"line_{line_no}:{w}" for w in warns])
            if normalized is None:
                dropped += 1
                continue
            events.append(normalized)

    return {
        "events": events,
        "normalizedEvents": len(events),
        "droppedEvents": dropped,
        "warnings": warnings,
        "warningsCount": len(warnings),
    }


def normalize_ws_events_file(in_path: Path, out_path: Path, include_raw: bool = False) -> dict[str, Any]:
    summary = collect_normalized_ws_events(in_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fp:
        for event in summary["events"]:
            row = dict(event)
            if not include_raw:
                row.pop("raw", None)
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "inPath": str(in_path),
        "outPath": str(out_path),
        "normalizedEvents": summary["normalizedEvents"],
        "droppedEvents": summary["droppedEvents"],
        "warningsCount": summary["warningsCount"],
    }


def _normalize_v1_passthrough(raw_row: dict[str, Any], event: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    ts_ms = _extract_ts_ms(raw_row, event)
    frame_seq = _extract_frame_seq(event) or _extract_frame_seq(raw_row)
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
        warnings.append("payload_not_object_defaulted")

    normalized: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "tsMs": ts_ms,
        "runId": _read_str(event, "runId") or _read_str(raw_row, "runId"),
        "frameSeq": frame_seq,
        "component": _normalize_component(_read_str(event, "component") or "unknown"),
        "category": _normalize_category(_read_str(event, "category") or "unknown"),
        "name": _read_str(event, "name") or "unknown",
        "phase": _normalize_phase(_read_str(event, "phase")),
        "status": _normalize_status(_read_str(event, "status")),
        "latencyMs": _extract_latency_ms(event),
        "payload": payload,
    }
    return normalized, warnings


def _normalize_legacy(raw_row: dict[str, Any], event: dict[str, Any], warnings: list[str]) -> dict[str, Any] | None:
    ts_ms = _extract_ts_ms(raw_row, event)
    frame_seq = _extract_frame_seq(event) or _extract_frame_seq(raw_row)
    component = _infer_component(event)
    name = _infer_name(event)
    category = _infer_category(name)
    phase = _infer_phase(event)
    status = _infer_status(event)
    latency_ms = _extract_latency_ms(event)
    run_id = _read_str(event, "runId") or _read_str(raw_row, "runId")

    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    payload = dict(payload)

    text_val = _extract_text(event)
    if text_val and "text" not in payload and name == "ocr.scan_text":
        payload["text"] = text_val

    hazards = _extract_hazards(event)
    if hazards and "hazards" not in payload and name in {"risk.hazards", "risk.depth"}:
        payload["hazards"] = hazards

    if status == "timeout" and name == "safety.confirm" and "reason" not in payload:
        payload["reason"] = "timeout"

    if not name:
        warnings.append("name_unrecognized")
        return None

    normalized = {
        "schemaVersion": SCHEMA_VERSION,
        "tsMs": ts_ms,
        "runId": run_id,
        "frameSeq": frame_seq,
        "component": component,
        "category": category,
        "name": name,
        "phase": phase,
        "status": status,
        "latencyMs": latency_ms,
        "payload": payload,
    }
    return normalized


def _extract_frame_seq(obj: Any) -> int | None:
    if not isinstance(obj, dict):
        return None
    for key in ("frameSeq", "frame_seq", "seq", "image_seq"):
        value = _to_int(obj.get(key))
        if value is not None and value > 0:
            return value

    for key in ("meta", "payload", "result"):
        nested = obj.get(key)
        if isinstance(nested, dict):
            value = _extract_frame_seq(nested)
            if value is not None:
                return value

    for key in ("frameId", "filename", "image", "path"):
        raw = obj.get(key)
        if not isinstance(raw, str):
            continue
        m = _FRAME_RE.search(raw)
        if m:
            parsed = _to_int(m.group(1))
            if parsed is not None and parsed > 0:
                return parsed
        # fallback: trailing number from filename
        n = _NUM_RE.search(raw)
        if n:
            parsed = _to_int(n.group(1))
            if parsed is not None and parsed > 0:
                return parsed
    return None


def _extract_ts_ms(raw_row: dict[str, Any], event: dict[str, Any]) -> int | None:
    for source in (event, raw_row):
        for key in ("tsMs", "timestampMs", "ts", "timestamp", "time", "receivedAtMs"):
            parsed = _to_ts_ms(source.get(key))
            if parsed is not None:
                return parsed
        for key in ("meta", "payload"):
            nested = source.get(key)
            if isinstance(nested, dict):
                for nested_key in ("tsMs", "timestampMs", "ts", "timestamp", "time"):
                    parsed = _to_ts_ms(nested.get(nested_key))
                    if parsed is not None:
                        return parsed
    return None


def _extract_latency_ms(event: dict[str, Any]) -> int | None:
    for key in ("latencyMs", "durationMs", "latency_ms", "duration_ms"):
        parsed = _to_int(event.get(key))
        if parsed is not None and parsed >= 0:
            return parsed

    start_ms = _to_ts_ms(event.get("startTs") or event.get("startMs") or event.get("start_ts"))
    end_ms = _to_ts_ms(event.get("endTs") or event.get("endMs") or event.get("end_ts"))
    if start_ms is not None and end_ms is not None and end_ms >= start_ms:
        return int(end_ms - start_ms)

    payload = event.get("payload")
    if isinstance(payload, dict):
        return _extract_latency_ms(payload)
    return None


def _infer_component(event: dict[str, Any]) -> str:
    component = _read_str(event, "component")
    if component:
        return _normalize_component(component)

    src_blob = " ".join(
        [
            _read_str(event, "source") or "",
            _read_str(event, "tool") or "",
            _read_str(event, "toolName") or "",
            _read_str(event, "category") or "",
        ]
    ).lower()
    if "unity" in src_blob:
        return "unity"
    if "gateway" in src_blob:
        return "gateway"
    if any(token in src_blob for token in ("real_", "cloud", "onnx", "vlm", "det", "ocr", "depth")):
        return "cloud"
    if "mock" in src_blob or "sim" in src_blob:
        return "sim"
    return "unknown"


def _infer_name(event: dict[str, Any]) -> str:
    blob = _event_blob(event)

    if _contains_any(blob, ["local_fallback", "safety_fallback", "on_device_fallback", "fallback_triggered"]):
        return "safety.local_fallback"
    if _contains_any(blob, ["preempt", "preemption"]):
        return "safety.preempt"
    if _contains_any(blob, ["critical_latch", "safety_lock", "latch", "emergency"]):
        return "safety.latch"
    if _contains_any(blob, ["confirm", "ask_user", "user_confirm", "clarify", "double_check"]):
        return "safety.confirm"

    hazards = _extract_hazards(event)
    if hazards:
        return "risk.hazards"

    if _contains_any(blob, ["depth", "dropoff", "stair", "hazard"]):
        return "risk.depth"
    if _contains_any(blob, ["ocr", "scan_text", "read_text", "text_reader", "text"]):
        return "ocr.scan_text"

    event_type = (_read_str(event, "type") or "").lower()
    if event_type:
        if event_type == "health":
            return "system.health"
        if event_type == "metric":
            return "metric.generic"
        if event_type == "scenario":
            return "scenario.event"
    return "unknown"


def _infer_category(name: str) -> str:
    if name.startswith("ocr.") or name.startswith("risk."):
        return "tool"
    if name.startswith("safety."):
        return "safety"
    if name.startswith("system."):
        return "system"
    if name.startswith("scenario."):
        return "scenario"
    if name.startswith("metric."):
        return "metric"
    return "unknown"


def _infer_phase(event: dict[str, Any]) -> str | None:
    explicit = _normalize_phase(_read_str(event, "phase"))
    if explicit is not None:
        return explicit

    blob = _event_blob(event)
    if _contains_any(blob, ["start", "request", "intent", "call", "confirm_request", "clarify", "double_check"]):
        return "start"
    if _contains_any(blob, ["result", "response", "done"]):
        return "result"
    if _contains_any(blob, ["error", "exception", "fail"]):
        return "error"
    if _contains_any(blob, ["info", "log"]):
        return "info"
    return None


def _infer_status(event: dict[str, Any]) -> str | None:
    explicit = _normalize_status(_read_str(event, "status"))
    if explicit is not None:
        return explicit

    blob = _event_blob(event)
    if _contains_any(blob, ["timeout", "expired"]):
        return "timeout"
    if _contains_any(blob, ["cancel", "canceled", "cancelled"]):
        return "cancel"
    if _contains_any(blob, ["error", "exception", "fail"]):
        return "error"
    if _contains_any(blob, ["result", "response", "done", "ok", "success"]):
        return "ok"
    return None


def _extract_text(event: dict[str, Any]) -> str:
    for key in ("text", "summary", "answerText", "instruction"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    payload = event.get("payload")
    if isinstance(payload, dict):
        for key in ("text", "summary", "answerText"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _extract_hazards(event: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def push(item: dict[str, Any], fallback: dict[str, Any] | None = None) -> None:
        kind = _read_str(item, "hazardKind") or _read_str(item, "kind") or _read_str(item, "type")
        if not kind:
            return
        severity = _read_str(item, "severity")
        row: dict[str, Any] = {"hazardKind": kind.strip().lower()}
        if severity:
            row["severity"] = severity.strip().lower()
        score = item.get("score")
        if score is None and fallback is not None:
            score = fallback.get("confidence")
        try:
            if score is not None:
                row["score"] = float(score)
        except Exception:
            pass
        evidence: dict[str, Any] = {}
        for key in ("distanceM", "azimuthDeg", "source"):
            value = item.get(key)
            if value is None and fallback is not None:
                value = fallback.get(key)
            if value is not None:
                evidence[key] = value
        if evidence:
            row["evidence"] = evidence
        out.append(row)

    for key in ("hazards", "risks", "depthHazards"):
        value = event.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    push(item)

    payload = event.get("payload")
    if isinstance(payload, dict):
        for key in ("hazards", "risks", "depthHazards"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        push(item, fallback=event)

    # Legacy single-risk style payloads used by older WS events.
    single_kind = _read_str(event, "hazardKind") or _read_str(event, "riskKind")
    if not single_kind and _read_str(event, "type") == "risk":
        single_kind = "obstacle_close"
    if single_kind:
        severity = _read_str(event, "riskLevel") or "warning"
        push({"hazardKind": single_kind, "severity": severity}, fallback=event)

    return out


def _event_blob(event: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("type", "name", "tool", "toolName", "source", "category", "summary", "message", "event", "status", "hazardKind", "riskLevel"):
        value = event.get(key)
        if value is not None:
            parts.append(str(value))
    payload = event.get("payload")
    if isinstance(payload, dict):
        for key in ("type", "name", "tool", "toolName", "source", "category", "summary", "message", "event", "status", "reason", "error"):
            value = payload.get(key)
            if value is not None:
                parts.append(str(value))
        if any(k in payload for k in ("choice", "confirmed", "yes", "no")):
            parts.append("confirm_result")
    return " ".join(parts).lower()


def _contains_any(text: str, keywords: list[str]) -> bool:
    blob = str(text or "").lower()
    return any(keyword in blob for keyword in keywords)


def _normalize_component(value: str) -> str:
    v = str(value or "").strip().lower()
    if v in {"unity", "gateway", "cloud", "sim"}:
        return v
    return "unknown"


def _normalize_category(value: str) -> str:
    v = str(value or "").strip().lower()
    if v in {"tool", "safety", "system", "scenario", "metric", "ui"}:
        return v
    return "unknown"


def _normalize_phase(value: str | None) -> str | None:
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in {"start", "result", "error", "info"}:
        return v
    return None


def _normalize_status(value: str | None) -> str | None:
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in {"ok", "timeout", "cancel", "error"}:
        return v
    if v in {"expired"}:
        return "timeout"
    if v in {"failed", "exception"}:
        return "error"
    return None


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def _to_ts_ms(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            raw = float(text)
        except ValueError:
            return None
    else:
        return None

    if raw <= 0:
        return None
    if raw < 10_000_000_000:
        raw *= 1000.0
    return int(raw)


def _read_str(obj: Any, key: str) -> str | None:
    if not isinstance(obj, dict):
        return None
    value = obj.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
