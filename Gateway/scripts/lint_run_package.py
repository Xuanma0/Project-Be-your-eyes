from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

try:
    import jsonschema
except Exception:  # noqa: BLE001
    jsonschema = None

from byes.event_normalizer import collect_normalized_ws_events
from byes.hazards.taxonomy_v1 import normalize_hazards
from byes.inference.seg_context import DEFAULT_SEG_CONTEXT_BUDGET, build_seg_context_from_events
from byes.schemas.pov_ir_schema import validate_pov_ir

_SHA_LINE_RE = re.compile(r"^([a-fA-F0-9]{64})\s+\*?(.+)$")
_SEG_SCHEMA_PATH = GATEWAY_ROOT / "contracts" / "byes.seg.v1.json"
_DEPTH_SCHEMA_PATH = GATEWAY_ROOT / "contracts" / "byes.depth.v1.json"
_PLAN_CONTEXT_PACK_SCHEMA_PATH = GATEWAY_ROOT / "contracts" / "plan.context_pack.v1.json"
_FRAME_E2E_SCHEMA_PATH = GATEWAY_ROOT / "contracts" / "frame.e2e.v1.json"
_FRAME_INPUT_SCHEMA_PATH = GATEWAY_ROOT / "contracts" / "frame.input.v1.json"
_FRAME_ACK_SCHEMA_PATH = GATEWAY_ROOT / "contracts" / "frame.ack.v1.json"


def _collect_hazard_stats_from_gt(path: Path) -> dict[str, Any]:
    unknown: set[str] = set()
    alias_hits = 0
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        hazards_raw = row.get("hazards")
        if not isinstance(hazards_raw, list):
            continue
        _normalized, warnings = normalize_hazards([item for item in hazards_raw if isinstance(item, dict)])
        for warning in warnings:
            text = str(warning or "").strip().lower()
            if text.startswith("unknown_kind:"):
                unknown.add(text.split(":", 1)[1].strip())
            elif text.startswith("alias:"):
                alias_hits += 1
    return {"unknownKinds": unknown, "aliasHits": alias_hits}


def _collect_hazard_stats_from_ws(path: Path) -> dict[str, Any]:
    unknown: set[str] = set()
    alias_hits = 0
    normalized = collect_normalized_ws_events(path)
    events = normalized.get("events", [])
    if not isinstance(events, list):
        events = []
    for event in events:
        if not isinstance(event, dict):
            continue
        name = str(event.get("name", "")).strip().lower()
        if name not in {"risk.hazards", "risk.depth"}:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        hazards_raw = payload.get("hazards")
        if not isinstance(hazards_raw, list):
            continue
        _normalized_hazards, warnings = normalize_hazards([item for item in hazards_raw if isinstance(item, dict)])
        for warning in warnings:
            text = str(warning or "").strip().lower()
            if text.startswith("unknown_kind:"):
                unknown.add(text.split(":", 1)[1].strip())
            elif text.startswith("alias:"):
                alias_hits += 1
    return {"unknownKinds": unknown, "aliasHits": alias_hits}


def _collect_risk_frame_seq_stats(path: Path, *, frames_declared: int) -> dict[str, int]:
    missing = 0
    out_of_range = 0
    normalized = collect_normalized_ws_events(path)
    events = normalized.get("events", [])
    if not isinstance(events, list):
        events = []
    for event in events:
        if not isinstance(event, dict):
            continue
        name = str(event.get("name", "")).strip().lower()
        if name not in {"risk.hazards", "risk.depth"}:
            continue
        frame_seq_raw = event.get("frameSeq")
        if not isinstance(frame_seq_raw, int):
            missing += 1
            continue
        frame_seq = int(frame_seq_raw)
        if frame_seq <= 0:
            out_of_range += 1
            continue
        if frames_declared > 0 and frame_seq > frames_declared:
            out_of_range += 1
    return {
        "riskEventMissingFrameSeq": missing,
        "riskEventFrameSeqOutOfRange": out_of_range,
    }


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            name = member.filename.replace("\\", "/")
            if name.startswith("/") or name.startswith("../") or "/../" in name:
                raise ValueError(f"unsafe zip entry: {member.filename}")
            resolved = (target_dir / member.filename).resolve()
            if not str(resolved).startswith(str(target_dir.resolve())):
                raise ValueError(f"zip path traversal detected: {member.filename}")
        zf.extractall(target_dir)


def _resolve_package_root(path: Path) -> tuple[Path, Path | None, str]:
    if path.is_dir():
        return path, None, "dir"
    if path.is_file() and path.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="lint_runpkg_"))
        _safe_extract_zip(path, tmp)
        if (tmp / "manifest.json").exists() or (tmp / "run_manifest.json").exists():
            return tmp, tmp, "zip"
        candidates = [p.parent for p in tmp.rglob("manifest.json")] + [p.parent for p in tmp.rglob("run_manifest.json")]
        if not candidates:
            raise FileNotFoundError("manifest not found in extracted run package")
        candidates.sort(key=lambda p: len(str(p)))
        return candidates[0], tmp, "zip"
    raise FileNotFoundError(f"run package path not found: {path}")


def _load_manifest(run_root: Path) -> tuple[Path, dict[str, Any]]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_root / name
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("manifest payload must be object")
            return path, payload
    raise FileNotFoundError("manifest.json not found")


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _discover_sha_lists(run_root: Path) -> list[Path]:
    files: list[Path] = []
    for item in run_root.iterdir():
        if not item.is_file():
            continue
        lower = item.name.lower()
        if "sha256" in lower or "hash" in lower or lower.endswith(".sha256"):
            files.append(item)
    return sorted(files)


def _read_sha_entries(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8-sig")
    try:
        payload = json.loads(text)
    except Exception:
        payload = None

    mapping: dict[str, str] = {}
    if isinstance(payload, dict):
        files = payload.get("files")
        if isinstance(files, list):
            for row in files:
                if not isinstance(row, dict):
                    continue
                rel = str(row.get("path") or row.get("file") or "").replace("\\", "/").strip()
                sha = str(row.get("sha256") or row.get("hash") or "").strip().lower()
                if rel and len(sha) == 64:
                    mapping[rel] = sha
            return mapping
        if payload and all(isinstance(k, str) and isinstance(v, str) for k, v in payload.items()):
            for k, v in payload.items():
                rel = str(k).replace("\\", "/").strip()
                sha = str(v).strip().lower()
                if rel and len(sha) == 64:
                    mapping[rel] = sha
            return mapping

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _SHA_LINE_RE.match(line)
        if not m:
            continue
        sha = m.group(1).lower()
        rel = m.group(2).replace("\\", "/").strip()
        mapping[rel] = sha
    return mapping


def _load_seg_contract_schema() -> dict[str, Any] | None:
    if not _SEG_SCHEMA_PATH.exists():
        return None
    try:
        payload = json.loads(_SEG_SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_depth_contract_schema() -> dict[str, Any] | None:
    if not _DEPTH_SCHEMA_PATH.exists():
        return None
    try:
        payload = json.loads(_DEPTH_SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_plan_context_pack_schema() -> dict[str, Any] | None:
    if not _PLAN_CONTEXT_PACK_SCHEMA_PATH.exists():
        return None
    try:
        payload = json.loads(_PLAN_CONTEXT_PACK_SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_frame_e2e_schema() -> dict[str, Any] | None:
    if not _FRAME_E2E_SCHEMA_PATH.exists():
        return None
    try:
        payload = json.loads(_FRAME_E2E_SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_frame_input_schema() -> dict[str, Any] | None:
    if not _FRAME_INPUT_SCHEMA_PATH.exists():
        return None
    try:
        payload = json.loads(_FRAME_INPUT_SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_frame_ack_schema() -> dict[str, Any] | None:
    if not _FRAME_ACK_SCHEMA_PATH.exists():
        return None
    try:
        payload = json.loads(_FRAME_ACK_SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _validate_seg_payload(
    payload: dict[str, Any],
    schema: dict[str, Any] | None,
) -> tuple[bool, int, int, int, int, int, int, int]:
    payload_ok = True
    bbox_out_of_range = 0
    score_out_of_range = 0
    empty_label = 0
    mask_present = 0
    mask_schema_ok = 0
    mask_size_mismatch = 0
    mask_bad_counts = 0

    if schema is not None and jsonschema is not None:
        try:
            jsonschema.validate(payload, schema)
        except Exception:
            payload_ok = False

    segments_raw = payload.get("segments")
    if not isinstance(segments_raw, list):
        return False, bbox_out_of_range, score_out_of_range, empty_label, mask_present, mask_schema_ok, mask_size_mismatch, mask_bad_counts

    image_width_raw = payload.get("imageWidth")
    image_height_raw = payload.get("imageHeight")
    image_width = int(image_width_raw) if isinstance(image_width_raw, int) and image_width_raw > 0 else None
    image_height = int(image_height_raw) if isinstance(image_height_raw, int) and image_height_raw > 0 else None

    for row in segments_raw:
        if not isinstance(row, dict):
            payload_ok = False
            bbox_out_of_range += 1
            continue
        label = str(row.get("label", "")).strip()
        if not label:
            empty_label += 1
            payload_ok = False

        score = _to_float(row.get("score"))
        if score is None or score < 0.0 or score > 1.0:
            score_out_of_range += 1
            payload_ok = False

        bbox = row.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            bbox_out_of_range += 1
            payload_ok = False
            continue
        coords: list[float] = []
        parse_failed = False
        for value in bbox:
            parsed = _to_float(value)
            if parsed is None:
                parse_failed = True
                break
            coords.append(parsed)
        if parse_failed:
            bbox_out_of_range += 1
            payload_ok = False
            continue
        x0, y0, x1, y1 = coords
        if not (x0 < x1 and y0 < y1):
            bbox_out_of_range += 1
            payload_ok = False
        if image_width is not None and not (0.0 <= x0 <= float(image_width) and 0.0 <= x1 <= float(image_width)):
            bbox_out_of_range += 1
            payload_ok = False
        if image_height is not None and not (0.0 <= y0 <= float(image_height) and 0.0 <= y1 <= float(image_height)):
            bbox_out_of_range += 1
            payload_ok = False

        if "mask" in row:
            mask_present += 1
            mask = row.get("mask")
            mask_ok, size_mismatch, bad_counts = _validate_seg_mask(mask)
            if mask_ok:
                mask_schema_ok += 1
            else:
                payload_ok = False
            mask_size_mismatch += int(size_mismatch)
            mask_bad_counts += int(bad_counts)

    return (
        payload_ok,
        bbox_out_of_range,
        score_out_of_range,
        empty_label,
        mask_present,
        mask_schema_ok,
        mask_size_mismatch,
        mask_bad_counts,
    )


def _validate_depth_payload(
    payload: dict[str, Any],
    schema: dict[str, Any] | None,
) -> tuple[bool, int, int, bool]:
    payload_ok = True
    grid_bad_size = 0
    grid_out_of_range = 0
    grid_present = False

    if schema is not None and jsonschema is not None:
        try:
            jsonschema.validate(payload, schema)
        except Exception:
            payload_ok = False

    grid = payload.get("grid")
    if not isinstance(grid, dict):
        return payload_ok, grid_bad_size, grid_out_of_range, grid_present

    grid_present = True
    fmt = str(grid.get("format", "")).strip()
    unit = str(grid.get("unit", "")).strip().lower()
    if fmt != "grid_u16_mm_v1" or unit != "mm":
        payload_ok = False
        grid_bad_size += 1
        return payload_ok, grid_bad_size, grid_out_of_range, grid_present

    size_raw = grid.get("size")
    if not isinstance(size_raw, list) or len(size_raw) != 2:
        payload_ok = False
        grid_bad_size += 1
        return payload_ok, grid_bad_size, grid_out_of_range, grid_present
    try:
        gw = int(size_raw[0])
        gh = int(size_raw[1])
    except Exception:
        payload_ok = False
        grid_bad_size += 1
        return payload_ok, grid_bad_size, grid_out_of_range, grid_present
    if gw <= 0 or gh <= 0:
        payload_ok = False
        grid_bad_size += 1
        return payload_ok, grid_bad_size, grid_out_of_range, grid_present

    values_raw = grid.get("values")
    if not isinstance(values_raw, list):
        payload_ok = False
        grid_bad_size += 1
        return payload_ok, grid_bad_size, grid_out_of_range, grid_present

    if len(values_raw) != gw * gh:
        payload_ok = False
        grid_bad_size += 1

    for value in values_raw:
        try:
            parsed = int(value)
        except Exception:
            payload_ok = False
            grid_out_of_range += 1
            continue
        if parsed < 0 or parsed > 65535:
            payload_ok = False
            grid_out_of_range += 1

    return payload_ok, grid_bad_size, grid_out_of_range, grid_present


def _validate_seg_mask(mask: Any) -> tuple[bool, int, int]:
    if not isinstance(mask, dict):
        return False, 1, 1
    fmt = str(mask.get("format", "")).strip()
    if fmt != "rle_v1":
        return False, 1, 1

    size_raw = mask.get("size")
    if not isinstance(size_raw, list) or len(size_raw) != 2:
        return False, 1, 1
    try:
        h = int(size_raw[0])
        w = int(size_raw[1])
    except Exception:
        return False, 1, 1
    if h <= 0 or w <= 0:
        return False, 1, 1

    counts_raw = mask.get("counts")
    if not isinstance(counts_raw, list):
        return False, 0, 1
    total = 0
    for value in counts_raw:
        try:
            parsed = int(value)
        except Exception:
            return False, 0, 1
        if parsed < 0:
            return False, 0, 1
        total += parsed

    if total != h * w:
        return False, 1, 1
    return True, 0, 0


def _seg_context_schema_ok(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("schemaVersion", "")).strip() != "seg.context.v1":
        return False
    budget = payload.get("budget")
    budget = budget if isinstance(budget, dict) else {}
    stats = payload.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    stats_out = stats.get("out")
    stats_out = stats_out if isinstance(stats_out, dict) else {}
    stats_truncation = stats.get("truncation")
    stats_truncation = stats_truncation if isinstance(stats_truncation, dict) else {}
    text = payload.get("text")
    text = text if isinstance(text, dict) else {}
    if not isinstance(text.get("promptFragment"), str):
        return False
    for key in ("maxChars", "maxSegments"):
        try:
            if int(budget.get(key, -1)) < 0:
                return False
        except Exception:
            return False
    for key in ("segments", "uniqueLabels", "charsTotal", "tokenApprox"):
        try:
            if int(stats_out.get(key, -1)) < 0:
                return False
        except Exception:
            return False
    for key in ("segmentsDropped", "labelsDropped", "charsDropped"):
        try:
            if int(stats_truncation.get(key, -1)) < 0:
                return False
        except Exception:
            return False
    return True


def _plan_context_alignment_schema_ok(payload: dict[str, Any]) -> tuple[bool, float, float, bool]:
    if not isinstance(payload, dict):
        return False, 0.0, 0.0, False
    if str(payload.get("schemaVersion", "")).strip() != "plan.context_alignment.v1":
        return False, 0.0, 0.0, False

    seg = payload.get("seg")
    seg = seg if isinstance(seg, dict) else {}
    pov = payload.get("pov")
    pov = pov if isinstance(pov, dict) else {}
    context_used = bool(payload.get("contextUsed"))

    for key in ("present", "hit"):
        if not isinstance(seg.get(key), bool):
            return False, 0.0, 0.0, context_used
        if not isinstance(pov.get(key), bool):
            return False, 0.0, 0.0, context_used

    for key in ("labelCount",):
        try:
            if int(seg.get(key, -1)) < 0:
                return False, 0.0, 0.0, context_used
        except Exception:
            return False, 0.0, 0.0, context_used
    for key in ("tokenCount", "hitCount"):
        try:
            if int(pov.get(key, -1)) < 0:
                return False, 0.0, 0.0, context_used
        except Exception:
            return False, 0.0, 0.0, context_used

    try:
        seg_coverage = float(seg.get("coverage", 0.0))
        pov_coverage = float(pov.get("coverage", 0.0))
    except Exception:
        return False, 0.0, 0.0, context_used
    if not (0.0 <= seg_coverage <= 1.0):
        return False, 0.0, 0.0, context_used
    if not (0.0 <= pov_coverage <= 1.0):
        return False, 0.0, 0.0, context_used

    matched = seg.get("matched")
    if not isinstance(matched, list):
        return False, 0.0, 0.0, context_used
    for item in matched:
        if not isinstance(item, str):
            return False, 0.0, 0.0, context_used

    return True, float(seg_coverage), float(pov_coverage), context_used


def _plan_context_pack_schema_ok(
    payload: dict[str, Any],
    schema: dict[str, Any] | None,
) -> tuple[bool, int, int]:
    if not isinstance(payload, dict):
        return False, 0, 0
    schema_ok = True
    if schema is not None and jsonschema is not None:
        try:
            jsonschema.validate(payload, schema)
        except Exception:
            schema_ok = False

    if str(payload.get("schemaVersion", "")).strip() != "plan.context_pack.v1":
        return False, 0, 0

    stats = payload.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    out_stats = stats.get("out")
    out_stats = out_stats if isinstance(out_stats, dict) else {}
    truncation = stats.get("truncation")
    truncation = truncation if isinstance(truncation, dict) else {}
    text = payload.get("text")
    text = text if isinstance(text, dict) else {}
    budget = payload.get("budget")
    budget = budget if isinstance(budget, dict) else {}

    if not isinstance(payload.get("runId"), str):
        return False, 0, 0
    if not isinstance(text.get("summary"), str) or not isinstance(text.get("prompt"), str):
        return False, 0, 0
    if not isinstance(budget.get("mode"), str):
        return False, 0, 0
    try:
        max_chars = int(budget.get("maxChars", -1))
        chars_total = int(out_stats.get("charsTotal", -1))
        token_approx = int(out_stats.get("tokenApprox", -1))
        chars_dropped = int(truncation.get("charsDropped", -1))
    except Exception:
        return False, 0, 0
    if max_chars < 0 or chars_total < 0 or token_approx < 0 or chars_dropped < 0:
        return False, 0, 0

    return bool(schema_ok), max(0, chars_total), max(0, chars_dropped)


def _frame_e2e_schema_ok(
    payload: dict[str, Any],
    schema: dict[str, Any] | None,
) -> tuple[bool, int, bool, bool]:
    if not isinstance(payload, dict):
        return False, 0, True, False
    schema_ok = True
    if schema is not None and jsonschema is not None:
        try:
            jsonschema.validate(payload, schema)
        except Exception:
            schema_ok = False

    if str(payload.get("schemaVersion", "")).strip() != "frame.e2e.v1":
        return False, 0, True, False
    if not isinstance(payload.get("runId"), str):
        return False, 0, True, False
    try:
        frame_seq = int(payload.get("frameSeq", 0))
        t0_ms = int(payload.get("t0Ms", -1))
        t1_ms = int(payload.get("t1Ms", -1))
        total_ms = int(payload.get("totalMs", -1))
    except Exception:
        return False, 0, True, False
    if frame_seq <= 0 or t0_ms < 0 or t1_ms < 0 or total_ms < 0:
        return False, 0, True, False
    if t1_ms < t0_ms:
        return False, 0, True, False

    parts = payload.get("partsMs")
    parts = parts if isinstance(parts, dict) else {}
    present = payload.get("present")
    present = present if isinstance(present, dict) else {}
    part_values: list[int | None] = []
    parts_sum = 0
    for key in ("segMs", "riskMs", "planMs", "executeMs", "confirmMs"):
        value = parts.get(key)
        if value is None:
            part_values.append(None)
            continue
        try:
            parsed = int(value)
        except Exception:
            return False, 0, True, False
        if parsed < 0:
            return False, 0, True, False
        part_values.append(parsed)
        parts_sum += int(parsed)
    for key in ("seg", "risk", "plan", "execute", "confirm"):
        if not isinstance(present.get(key), bool):
            return False, 0, True, False
    parts_missing = all(value is None for value in part_values)
    parts_sum_gt_total = parts_sum > max(0, total_ms) if not parts_missing else False
    return bool(schema_ok), max(0, total_ms), bool(parts_missing), bool(parts_sum_gt_total)


def _frame_input_schema_ok(payload: dict[str, Any], schema: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    schema_ok = True
    if schema is not None and jsonschema is not None:
        try:
            jsonschema.validate(payload, schema)
        except Exception:
            schema_ok = False

    if str(payload.get("schemaVersion", "")).strip() != "frame.input.v1":
        return False
    if not isinstance(payload.get("runId"), str):
        return False
    try:
        frame_seq = int(payload.get("frameSeq", 0))
        recv_ts_ms = int(payload.get("recvTsMs", -1))
    except Exception:
        return False
    if frame_seq <= 0 or recv_ts_ms < 0:
        return False
    capture_raw = payload.get("captureTsMs")
    if capture_raw is not None:
        try:
            capture_ts_ms = int(capture_raw)
        except Exception:
            return False
        if capture_ts_ms < 0:
            return False
    meta = payload.get("meta")
    if meta is not None and not isinstance(meta, dict):
        return False
    if isinstance(meta, dict):
        device_time_base = meta.get("deviceTimeBase")
        if device_time_base is not None:
            text = str(device_time_base).strip()
            if text not in {"unix_ms", "monotonic_ms"}:
                return False
        device_id = meta.get("deviceId")
        if device_id is not None and not isinstance(device_id, str):
            return False
    return bool(schema_ok)


def _frame_ack_schema_ok(payload: dict[str, Any], schema: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    schema_ok = True
    if schema is not None and jsonschema is not None:
        try:
            jsonschema.validate(payload, schema)
        except Exception:
            schema_ok = False

    if str(payload.get("schemaVersion", "")).strip() != "frame.ack.v1":
        return False
    if not isinstance(payload.get("runId"), str):
        return False
    try:
        frame_seq = int(payload.get("frameSeq", 0))
        feedback_ts_ms = int(payload.get("feedbackTsMs", -1))
    except Exception:
        return False
    if frame_seq <= 0 or feedback_ts_ms < 0:
        return False
    kind = str(payload.get("kind", "")).strip().lower()
    if kind not in {"tts", "overlay", "haptic", "any"}:
        return False
    if not isinstance(payload.get("accepted"), bool):
        return False
    return bool(schema_ok)


def _percentile_float(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = max(0.0, min(1.0, p / 100.0))
    idx = int(math.ceil(rank * len(ordered)) - 1)
    idx = max(0, min(len(ordered) - 1, idx))
    return float(ordered[idx])


def _normalize_frame_ack_kind_bucket(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw == "tts":
        return "tts"
    if raw in {"overlay", "ar"}:
        return "ar"
    if raw == "haptic":
        return "haptic"
    return "other"


def lint_run_package(run_package: Path, strict: bool = False, *, quiet: bool = False) -> tuple[int, dict[str, Any]]:
    warnings: list[str] = []
    errors: list[str] = []
    cleanup_dir: Path | None = None

    try:
        run_root, cleanup_dir, source_type = _resolve_package_root(run_package)
        manifest_path, manifest = _load_manifest(run_root)

        frames_dir_rel = str(manifest.get("framesDir", "frames") or "frames")
        frames_meta_rel = str(manifest.get("framesMetaJsonl", "frames_meta.jsonl") or "frames_meta.jsonl")
        frames_count_declared = int(manifest.get("framesCount", manifest.get("frameCountSent", 0)) or 0)

        frames_dir = run_root / frames_dir_rel
        frames_meta_path = run_root / frames_meta_rel

        if not frames_dir.exists():
            errors.append(f"framesDir missing: {frames_dir_rel}")
        if not frames_meta_path.exists():
            warnings.append(f"framesMetaJsonl missing: {frames_meta_rel}")

        frame_files: list[Path] = []
        if frames_dir.exists():
            for pattern in ("frame_*.jpg", "frame_*.jpeg", "frame_*.png"):
                frame_files.extend(frames_dir.glob(pattern))
            frame_files = sorted(frame_files)
        frame_count_actual = len(frame_files)
        if frames_count_declared > 0 and frame_count_actual != frames_count_declared:
            warnings.append(
                f"frames count mismatch declared={frames_count_declared} actual={frame_count_actual}"
            )

        gt = manifest.get("groundTruth")
        gt_covered = 0
        hazard_unknown_kinds: set[str] = set()
        hazard_alias_hits = 0
        risk_event_missing_frame_seq = 0
        risk_event_frame_seq_out_of_range = 0
        if isinstance(gt, dict):
            for key in ("ocrJsonl", "riskJsonl"):
                rel = str(gt.get(key, "")).strip()
                if not rel:
                    continue
                path = run_root / rel
                if not path.exists():
                    warnings.append(f"groundTruth file missing: {rel}")
                    continue
                has_seq = False
                for line in path.read_text(encoding="utf-8-sig").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(row, dict) and isinstance(row.get("frameSeq"), int):
                        has_seq = True
                        break
                if has_seq:
                    gt_covered += 1
                else:
                    warnings.append(f"groundTruth has no valid frameSeq: {rel}")
                if key == "riskJsonl":
                    gt_kind_stats = _collect_hazard_stats_from_gt(path)
                    hazard_unknown_kinds.update(gt_kind_stats["unknownKinds"])
                    hazard_alias_hits += int(gt_kind_stats["aliasHits"])

        events_v1_rel = str(manifest.get("eventsV1Jsonl", "") or "").strip()
        events_v1_present = 1 if events_v1_rel else 0
        events_v1_lines = 0
        events_v1_schema_ok = 0
        events_v1_normalized = 0
        events_v1_path: Path | None = None
        events_v1_rows: list[dict[str, Any]] = []
        pov_events_count = 0
        pov_decision_events_count = 0
        seg_events_present = 0
        seg_lines = 0
        seg_schema_ok = 0
        seg_normalized = 0
        seg_warnings_count = 0
        seg_prompt_events_present = 0
        seg_prompt_lines = 0
        seg_prompt_schema_ok = 0
        seg_prompt_warnings_count = 0
        seg_prompt_budget_present = 0
        seg_prompt_truncation_present = 0
        seg_prompt_out_present = 0
        seg_prompt_packed_true_count = 0
        seg_payload_schema_ok = 0
        seg_bbox_out_of_range_count = 0
        seg_score_out_of_range_count = 0
        seg_empty_label_count = 0
        seg_mask_present = 0
        seg_mask_schema_ok = 0
        seg_mask_size_mismatch_count = 0
        seg_mask_bad_counts_count = 0
        seg_context_present = 0
        seg_context_schema_ok = 0
        seg_context_chars = 0
        seg_context_segments_out = 0
        seg_context_trunc_segments_dropped = 0
        depth_events_present = 0
        depth_lines = 0
        depth_schema_ok = 0
        depth_normalized = 0
        depth_payload_schema_ok = 0
        depth_grid_present_count = 0
        depth_grid_bad_size_count = 0
        depth_grid_out_of_range_count = 0
        plan_request_events_present = 0
        plan_request_lines = 0
        plan_request_schema_ok = 0
        plan_request_seg_included_count = 0
        plan_request_seg_chars_total = 0
        plan_context_events_present = 0
        plan_context_lines = 0
        plan_context_schema_ok = 0
        plan_ctx_used_true_count = 0
        plan_seg_coverages: list[float] = []
        plan_pov_coverages: list[float] = []
        plan_context_pack_present = 0
        plan_context_pack_lines = 0
        plan_context_pack_schema_ok = 0
        plan_context_pack_chars: list[float] = []
        plan_context_pack_trunc_dropped_total = 0
        frame_e2e_events_present = 0
        frame_e2e_lines = 0
        frame_e2e_schema_ok = 0
        frame_e2e_total_ms_values: list[float] = []
        frame_e2e_parts_missing_count = 0
        frame_e2e_duplicate_count = 0
        frame_e2e_parts_sum_gt_total_count = 0
        frame_e2e_seen_keys: dict[tuple[str, int], int] = {}
        frame_input_events_present = 0
        frame_input_lines = 0
        frame_input_schema_ok = 0
        frame_ack_events_present = 0
        frame_ack_lines = 0
        frame_ack_schema_ok = 0
        frame_ack_kinds_present: set[str] = set()
        frame_ack_tts_count = 0
        frame_ack_ar_count = 0
        frame_ack_haptic_count = 0
        frame_user_e2e_events_present = 0
        frame_user_e2e_lines = 0
        frame_user_e2e_schema_ok = 0
        frame_user_e2e_negative_count = 0
        frame_user_e2e_duplicate_count = 0
        frame_user_e2e_seen_keys: dict[tuple[str, int], int] = {}
        seg_schema = _load_seg_contract_schema()
        depth_schema = _load_depth_contract_schema()
        plan_context_pack_schema = _load_plan_context_pack_schema()
        frame_e2e_schema = _load_frame_e2e_schema()
        frame_input_schema = _load_frame_input_schema()
        frame_ack_schema = _load_frame_ack_schema()
        if events_v1_rel:
            events_v1_path = run_root / events_v1_rel
            if not events_v1_path.exists():
                warnings.append(f"eventsV1Jsonl missing: {events_v1_rel}")
            else:
                try:
                    with events_v1_path.open("r", encoding="utf-8-sig") as fp:
                        for raw_line in fp:
                            line = raw_line.strip()
                            if not line:
                                continue
                            events_v1_lines += 1
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            if isinstance(obj, dict):
                                events_v1_rows.append(obj)
                                if str(obj.get("schemaVersion", "")).strip() == "byes.event.v1":
                                    events_v1_schema_ok += 1
                                name = str(obj.get("name", "")).strip().lower()
                                if name.startswith("pov."):
                                    pov_events_count += 1
                                if name == "pov.decision":
                                    pov_decision_events_count += 1
                                if name == "seg.prompt":
                                    seg_prompt_events_present = 1
                                    seg_prompt_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    payload_ok = True
                                    for key in ("targetsCount", "textChars", "boxesCount", "pointsCount"):
                                        if key not in payload:
                                            payload_ok = False
                                            seg_prompt_warnings_count += 1
                                            continue
                                        try:
                                            value = int(payload.get(key, 0))
                                        except Exception:
                                            payload_ok = False
                                            seg_prompt_warnings_count += 1
                                            continue
                                        if value < 0:
                                            payload_ok = False
                                            seg_prompt_warnings_count += 1
                                    prompt_version = payload.get("promptVersion")
                                    if prompt_version is not None and not isinstance(prompt_version, str):
                                        payload_ok = False
                                        seg_prompt_warnings_count += 1
                                    for key in ("backend", "model", "endpoint"):
                                        value = payload.get(key)
                                        if value is not None and not isinstance(value, str):
                                            payload_ok = False
                                            seg_prompt_warnings_count += 1
                                    budget_payload = payload.get("budget")
                                    if isinstance(budget_payload, dict):
                                        budget_ok = True
                                        for key in ("maxChars", "maxTargets", "maxBoxes", "maxPoints"):
                                            try:
                                                value = int(budget_payload.get(key, 0))
                                            except Exception:
                                                budget_ok = False
                                                seg_prompt_warnings_count += 1
                                                continue
                                            if value < 0:
                                                budget_ok = False
                                                seg_prompt_warnings_count += 1
                                        mode = budget_payload.get("mode")
                                        if mode is not None and not isinstance(mode, str):
                                            budget_ok = False
                                            seg_prompt_warnings_count += 1
                                        if budget_ok:
                                            seg_prompt_budget_present += 1
                                    out_payload = payload.get("out")
                                    if isinstance(out_payload, dict):
                                        out_ok = True
                                        for key in ("targetsCount", "textChars", "boxesCount", "pointsCount", "charsTotal"):
                                            try:
                                                value = int(out_payload.get(key, 0))
                                            except Exception:
                                                out_ok = False
                                                seg_prompt_warnings_count += 1
                                                continue
                                            if value < 0:
                                                out_ok = False
                                                seg_prompt_warnings_count += 1
                                        if out_ok:
                                            seg_prompt_out_present += 1
                                    truncation_payload = payload.get("truncation")
                                    if isinstance(truncation_payload, dict):
                                        truncation_ok = True
                                        for key in ("targetsDropped", "boxesDropped", "pointsDropped", "textCharsDropped"):
                                            try:
                                                value = int(truncation_payload.get(key, 0))
                                            except Exception:
                                                truncation_ok = False
                                                seg_prompt_warnings_count += 1
                                                continue
                                            if value < 0:
                                                truncation_ok = False
                                                seg_prompt_warnings_count += 1
                                        if truncation_ok:
                                            seg_prompt_truncation_present += 1
                                    packed_raw = payload.get("packed")
                                    if isinstance(packed_raw, bool):
                                        if packed_raw:
                                            seg_prompt_packed_true_count += 1
                                    elif packed_raw is not None:
                                        seg_prompt_warnings_count += 1
                                    if payload_ok:
                                        seg_prompt_schema_ok += 1
                                if name == "frame.input":
                                    frame_input_events_present = 1
                                    frame_input_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    if _frame_input_schema_ok(payload, frame_input_schema):
                                        frame_input_schema_ok += 1
                                    else:
                                        warnings.append("frame.input payload missing required fields")
                                if name == "frame.ack":
                                    frame_ack_events_present = 1
                                    frame_ack_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    ack_kind_bucket = _normalize_frame_ack_kind_bucket(payload.get("kind"))
                                    frame_ack_kinds_present.add(ack_kind_bucket)
                                    if ack_kind_bucket == "tts":
                                        frame_ack_tts_count += 1
                                    elif ack_kind_bucket == "ar":
                                        frame_ack_ar_count += 1
                                    elif ack_kind_bucket == "haptic":
                                        frame_ack_haptic_count += 1
                                    if _frame_ack_schema_ok(payload, frame_ack_schema):
                                        frame_ack_schema_ok += 1
                                    else:
                                        warnings.append("frame.ack payload missing required fields")
                                if name == "plan.request":
                                    plan_request_events_present = 1
                                    plan_request_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    schema_ok = (
                                        str(payload.get("schemaVersion", "")).strip() == "byes.plan_request.v1"
                                        and isinstance(payload.get("provider"), str)
                                        and isinstance(payload.get("promptVersion"), str)
                                    )
                                    seg_included = bool(payload.get("segIncluded"))
                                    try:
                                        seg_chars = max(0, int(payload.get("segChars", 0)))
                                    except Exception:
                                        seg_chars = 0
                                    if schema_ok:
                                        plan_request_schema_ok += 1
                                    else:
                                        warnings.append("plan.request payload missing required fields")
                                    if seg_included:
                                        plan_request_seg_included_count += 1
                                    plan_request_seg_chars_total += int(max(0, seg_chars))
                                if name == "plan.context_alignment":
                                    plan_context_events_present = 1
                                    plan_context_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    schema_ok, seg_cov, pov_cov, ctx_used = _plan_context_alignment_schema_ok(payload)
                                    if schema_ok:
                                        plan_context_schema_ok += 1
                                        plan_seg_coverages.append(float(seg_cov))
                                        plan_pov_coverages.append(float(pov_cov))
                                        if ctx_used:
                                            plan_ctx_used_true_count += 1
                                    else:
                                        warnings.append("plan.context_alignment payload missing required fields")
                                if name == "plan.context_pack":
                                    plan_context_pack_present = 1
                                    plan_context_pack_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    schema_ok, chars_total, chars_dropped = _plan_context_pack_schema_ok(
                                        payload,
                                        plan_context_pack_schema,
                                    )
                                    if schema_ok:
                                        plan_context_pack_schema_ok += 1
                                        plan_context_pack_chars.append(float(chars_total))
                                        plan_context_pack_trunc_dropped_total += int(max(0, chars_dropped))
                                    else:
                                        warnings.append("plan.context_pack payload missing required fields")
                                if name == "frame.e2e":
                                    frame_e2e_events_present = 1
                                    frame_e2e_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    frame_run_id = str(payload.get("runId", "")).strip() or str(obj.get("runId", "")).strip()
                                    frame_seq_raw = payload.get("frameSeq")
                                    if frame_seq_raw is None:
                                        frame_seq_raw = obj.get("frameSeq")
                                    try:
                                        frame_seq_value = int(frame_seq_raw)
                                    except Exception:
                                        frame_seq_value = 0
                                    if frame_run_id and frame_seq_value > 0:
                                        frame_key = (frame_run_id, frame_seq_value)
                                        frame_e2e_seen_keys[frame_key] = int(frame_e2e_seen_keys.get(frame_key, 0)) + 1
                                    schema_ok, total_ms, parts_missing, parts_sum_gt_total = _frame_e2e_schema_ok(
                                        payload,
                                        frame_e2e_schema,
                                    )
                                    if schema_ok:
                                        frame_e2e_schema_ok += 1
                                        frame_e2e_total_ms_values.append(float(total_ms))
                                    else:
                                        warnings.append("frame.e2e payload missing required fields")
                                    if parts_missing:
                                        frame_e2e_parts_missing_count += 1
                                    if parts_sum_gt_total:
                                        frame_e2e_parts_sum_gt_total_count += 1
                                if name == "frame.user_e2e":
                                    frame_user_e2e_events_present = 1
                                    frame_user_e2e_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    frame_run_id = str(payload.get("runId", "")).strip() or str(obj.get("runId", "")).strip()
                                    frame_seq_raw = payload.get("frameSeq")
                                    if frame_seq_raw is None:
                                        frame_seq_raw = obj.get("frameSeq")
                                    try:
                                        frame_seq_value = int(frame_seq_raw)
                                    except Exception:
                                        frame_seq_value = 0
                                    if frame_run_id and frame_seq_value > 0:
                                        frame_key = (frame_run_id, frame_seq_value)
                                        frame_user_e2e_seen_keys[frame_key] = int(
                                            frame_user_e2e_seen_keys.get(frame_key, 0)
                                        ) + 1

                                    t0_raw = payload.get("t0Ms")
                                    t1_raw = payload.get("t1Ms")
                                    try:
                                        t0_ms = int(t0_raw) if t0_raw is not None else None
                                        t1_ms = int(t1_raw) if t1_raw is not None else None
                                    except Exception:
                                        t0_ms = None
                                        t1_ms = None
                                    if t0_ms is not None and t1_ms is not None and int(t1_ms) < int(t0_ms):
                                        frame_user_e2e_negative_count += 1

                                    schema_ok, _total_ms, _parts_missing, _parts_sum_gt_total = _frame_e2e_schema_ok(
                                        payload,
                                        frame_e2e_schema,
                                    )
                                    if schema_ok:
                                        frame_user_e2e_schema_ok += 1
                                    else:
                                        warnings.append("frame.user_e2e payload missing required fields")
                                if name == "seg.segment":
                                    seg_events_present = 1
                                    seg_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    has_segments_count = isinstance(payload.get("segmentsCount"), (int, float))
                                    has_segments = isinstance(payload.get("segments"), list)
                                    if (
                                        str(obj.get("schemaVersion", "")).strip() == "byes.event.v1"
                                        and str(obj.get("category", "")).strip().lower() == "tool"
                                        and str(obj.get("phase", "")).strip().lower() == "result"
                                        and str(obj.get("status", "")).strip().lower() == "ok"
                                        and (has_segments_count or has_segments)
                                    ):
                                        seg_schema_ok += 1
                                    else:
                                        seg_warnings_count += 1
                                    (
                                        payload_ok,
                                        bbox_oor,
                                        score_oor,
                                        empty_label,
                                        mask_present,
                                        mask_schema_ok,
                                        mask_size_mismatch,
                                        mask_bad_counts,
                                    ) = _validate_seg_payload(payload, seg_schema)
                                    if payload_ok:
                                        seg_payload_schema_ok += 1
                                    else:
                                        seg_warnings_count += 1
                                    seg_bbox_out_of_range_count += int(bbox_oor)
                                    seg_score_out_of_range_count += int(score_oor)
                                    seg_empty_label_count += int(empty_label)
                                    seg_mask_present += int(mask_present)
                                    seg_mask_schema_ok += int(mask_schema_ok)
                                    seg_mask_size_mismatch_count += int(mask_size_mismatch)
                                    seg_mask_bad_counts_count += int(mask_bad_counts)
                                if name == "depth.estimate":
                                    depth_events_present = 1
                                    depth_lines += 1
                                    payload = obj.get("payload")
                                    payload = payload if isinstance(payload, dict) else {}
                                    has_grid_count = isinstance(payload.get("gridCount"), (int, float))
                                    has_grid = isinstance(payload.get("grid"), dict)
                                    if (
                                        str(obj.get("schemaVersion", "")).strip() == "byes.event.v1"
                                        and str(obj.get("category", "")).strip().lower() == "tool"
                                        and str(obj.get("phase", "")).strip().lower() == "result"
                                        and str(obj.get("status", "")).strip().lower() == "ok"
                                        and (has_grid_count or has_grid)
                                    ):
                                        depth_schema_ok += 1
                                    else:
                                        warnings.append("depth.estimate envelope invalid")
                                    depth_ok, grid_bad_size, grid_oor, grid_present = _validate_depth_payload(
                                        payload,
                                        depth_schema,
                                    )
                                    if depth_ok:
                                        depth_payload_schema_ok += 1
                                    else:
                                        warnings.append("depth.estimate payload invalid")
                                    depth_grid_bad_size_count += int(grid_bad_size)
                                    depth_grid_out_of_range_count += int(grid_oor)
                                    if grid_present:
                                        depth_grid_present_count += 1
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"eventsV1 read failed: {exc}")
                events_v1_norm = collect_normalized_ws_events(events_v1_path)
                events_v1_normalized = int(events_v1_norm.get("normalizedEvents", 0) or 0)
                warnings.extend(events_v1_norm.get("warnings", []))
                seg_normalized = len(
                    [
                        event
                        for event in (events_v1_norm.get("events", []) if isinstance(events_v1_norm.get("events"), list) else [])
                        if isinstance(event, dict) and str(event.get("name", "")).strip().lower() == "seg.segment"
                    ]
                )
                depth_normalized = len(
                    [
                        event
                        for event in (events_v1_norm.get("events", []) if isinstance(events_v1_norm.get("events"), list) else [])
                        if isinstance(event, dict) and str(event.get("name", "")).strip().lower() == "depth.estimate"
                    ]
                )
                seg_context_budget = {
                    "maxChars": int(DEFAULT_SEG_CONTEXT_BUDGET["maxChars"]),
                    "maxSegments": int(DEFAULT_SEG_CONTEXT_BUDGET["maxSegments"]),
                    "mode": str(DEFAULT_SEG_CONTEXT_BUDGET["mode"]),
                }
                seg_context_payload = build_seg_context_from_events(events_v1_rows, budget=seg_context_budget)
                seg_context_stats = seg_context_payload.get("stats")
                seg_context_stats = seg_context_stats if isinstance(seg_context_stats, dict) else {}
                seg_context_out = seg_context_stats.get("out")
                seg_context_out = seg_context_out if isinstance(seg_context_out, dict) else {}
                seg_context_truncation = seg_context_stats.get("truncation")
                seg_context_truncation = seg_context_truncation if isinstance(seg_context_truncation, dict) else {}
                seg_context_segments_out = int(seg_context_out.get("segments", 0) or 0)
                seg_context_chars = int(seg_context_out.get("charsTotal", 0) or 0)
                seg_context_trunc_segments_dropped = int(seg_context_truncation.get("segmentsDropped", 0) or 0)
                seg_context_present = int(seg_context_segments_out > 0)
                seg_context_schema_ok = int(_seg_context_schema_ok(seg_context_payload))
                frame_e2e_duplicate_count = int(
                    sum(max(0, int(count) - 1) for count in frame_e2e_seen_keys.values())
                )
                frame_user_e2e_duplicate_count = int(
                    sum(max(0, int(count) - 1) for count in frame_user_e2e_seen_keys.values())
                )

        pov_ir_present = 0
        pov_ir_schema_ok = 0
        pov_ir_decisions = 0
        pov_consistency_warnings = 0
        pov_rel = str(manifest.get("povIrJson", "") or "").strip()
        if pov_rel:
            pov_ir_present = 1
            pov_path = run_root / pov_rel
            if not pov_path.exists():
                errors.append(f"povIrJson missing: {pov_rel}")
            else:
                try:
                    pov_payload = json.loads(pov_path.read_text(encoding="utf-8-sig"))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"povIrJson parse failed: {pov_rel} ({exc})")
                    pov_payload = None
                if isinstance(pov_payload, dict):
                    decisions = pov_payload.get("decisionPoints")
                    if isinstance(decisions, list):
                        pov_ir_decisions = len([row for row in decisions if isinstance(row, dict)])
                    schema_ok, schema_errors = validate_pov_ir(pov_payload, strict=True)
                    if schema_ok:
                        pov_ir_schema_ok = int(pov_ir_decisions)
                    else:
                        for item in schema_errors:
                            errors.append(f"povIrJson schema: {item}")

        if pov_ir_decisions > 0 and events_v1_lines > 0 and pov_decision_events_count == 0:
            msg = "pov consistency: decisionPoints present but events_v1 has no pov.decision"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)
                pov_consistency_warnings += 1
        if pov_events_count > 0 and pov_ir_present == 0:
            msg = "pov consistency: events_v1 contains pov.* but manifest has no povIrJson"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)
                pov_consistency_warnings += 1

        ws_rel = str(manifest.get("wsJsonl", "ws_events.jsonl") or "ws_events.jsonl")
        ws_path = run_root / ws_rel
        if not ws_path.exists():
            if events_v1_path is not None and events_v1_path.exists():
                warnings.append(f"ws jsonl missing: {ws_rel} (using eventsV1Jsonl for normalization stats)")
                norm = collect_normalized_ws_events(events_v1_path)
                warnings.extend(norm.get("warnings", []))
                ws_kind_stats = _collect_hazard_stats_from_ws(events_v1_path)
                hazard_unknown_kinds.update(ws_kind_stats["unknownKinds"])
                hazard_alias_hits += int(ws_kind_stats["aliasHits"])
                risk_seq_stats = _collect_risk_frame_seq_stats(events_v1_path, frames_declared=frames_count_declared)
                risk_event_missing_frame_seq += int(risk_seq_stats.get("riskEventMissingFrameSeq", 0) or 0)
                risk_event_frame_seq_out_of_range += int(risk_seq_stats.get("riskEventFrameSeqOutOfRange", 0) or 0)
            else:
                errors.append(f"ws jsonl missing: {ws_rel}")
                norm = {"normalizedEvents": 0, "droppedEvents": 0, "warningsCount": 0}
        else:
            norm = collect_normalized_ws_events(ws_path)
            warnings.extend(norm.get("warnings", []))
            ws_kind_stats = _collect_hazard_stats_from_ws(ws_path)
            hazard_unknown_kinds.update(ws_kind_stats["unknownKinds"])
            hazard_alias_hits += int(ws_kind_stats["aliasHits"])
            risk_seq_stats = _collect_risk_frame_seq_stats(ws_path, frames_declared=frames_count_declared)
            risk_event_missing_frame_seq += int(risk_seq_stats.get("riskEventMissingFrameSeq", 0) or 0)
            risk_event_frame_seq_out_of_range += int(risk_seq_stats.get("riskEventFrameSeqOutOfRange", 0) or 0)

        if hazard_unknown_kinds:
            msg = f"unknown hazard kinds: {', '.join(sorted(hazard_unknown_kinds))}"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)

        sha_files = _discover_sha_lists(run_root)
        sha_checked = 0
        sha_mismatch = 0
        if sha_files:
            expected_paths = [manifest_path]
            gt_dir = run_root / "ground_truth"
            if gt_dir.exists():
                expected_paths.extend(sorted(gt_dir.glob("*.jsonl")))

            for sha_file in sha_files:
                mapping = _read_sha_entries(sha_file)
                for fpath in expected_paths:
                    rel = fpath.relative_to(run_root).as_posix()
                    if rel not in mapping:
                        continue
                    sha_checked += 1
                    actual = _sha256(fpath)
                    if mapping[rel] != actual:
                        sha_mismatch += 1
                        msg = f"sha mismatch in {sha_file.name} for {rel}"
                        if strict:
                            errors.append(msg)
                        else:
                            warnings.append(msg)

        summary = {
            "sourceType": source_type,
            "runRoot": str(run_root),
            "framesDeclared": frames_count_declared,
            "framesActual": frame_count_actual,
            "groundTruthFilesWithCoverage": gt_covered,
            "normalizedEvents": int(norm.get("normalizedEvents", 0) or 0),
            "droppedEvents": int(norm.get("droppedEvents", 0) or 0),
            "warningsCount": len(warnings),
            "errorsCount": len(errors),
            "shaChecked": sha_checked,
            "shaMismatch": sha_mismatch,
            "eventsV1Present": events_v1_present,
            "eventsV1Lines": events_v1_lines,
            "eventsV1SchemaOk": events_v1_schema_ok,
            "eventsV1Normalized": events_v1_normalized,
            "povIrPresent": int(pov_ir_present),
            "povIrSchemaOk": int(pov_ir_schema_ok),
            "povIrDecisions": int(pov_ir_decisions),
            "povEventsCount": int(pov_events_count),
            "povConsistencyWarnings": int(pov_consistency_warnings),
            "segEventsPresent": int(seg_events_present),
            "segLines": int(seg_lines),
            "segSchemaOk": int(seg_schema_ok),
            "segPayloadSchemaOk": int(seg_lines > 0 and seg_payload_schema_ok == seg_lines),
            "segNormalized": int(seg_normalized),
            "segWarningsCount": int(seg_warnings_count),
            "segPromptEventsPresent": int(seg_prompt_events_present),
            "segPromptLines": int(seg_prompt_lines),
            "segPromptSchemaOk": int(seg_prompt_schema_ok),
            "segPromptPayloadSchemaOk": int(seg_prompt_lines > 0 and seg_prompt_schema_ok == seg_prompt_lines),
            "segPromptWarningsCount": int(seg_prompt_warnings_count),
            "segPromptBudgetPresent": int(seg_prompt_budget_present),
            "segPromptTruncationPresent": int(seg_prompt_truncation_present),
            "segPromptOutPresent": int(seg_prompt_out_present),
            "segPromptPackedTrueCount": int(seg_prompt_packed_true_count),
            "segBboxOutOfRangeCount": int(seg_bbox_out_of_range_count),
            "segScoreOutOfRangeCount": int(seg_score_out_of_range_count),
            "segEmptyLabelCount": int(seg_empty_label_count),
            "segMaskPresent": int(seg_mask_present),
            "segMaskSchemaOk": int(seg_mask_schema_ok),
            "segMaskSizeMismatchCount": int(seg_mask_size_mismatch_count),
            "segMaskBadCountsCount": int(seg_mask_bad_counts_count),
            "segContextPresent": int(seg_context_present),
            "segContextSchemaOk": int(seg_context_schema_ok),
            "segContextChars": int(seg_context_chars),
            "segContextSegmentsOut": int(seg_context_segments_out),
            "segContextTruncSegmentsDropped": int(seg_context_trunc_segments_dropped),
            "depthEventsPresent": int(depth_events_present),
            "depthLines": int(depth_lines),
            "depthSchemaOk": int(depth_schema_ok),
            "depthPayloadSchemaOk": int(depth_lines > 0 and depth_payload_schema_ok == depth_lines),
            "depthNormalized": int(depth_normalized),
            "depthGridPresentCount": int(depth_grid_present_count),
            "depthGridBadSizeCount": int(depth_grid_bad_size_count),
            "depthGridOutOfRangeCount": int(depth_grid_out_of_range_count),
            "planRequestEventsPresent": int(plan_request_events_present),
            "planRequestLines": int(plan_request_lines),
            "planRequestSchemaOk": int(plan_request_lines > 0 and plan_request_schema_ok == plan_request_lines),
            "planRequestSegIncludedCount": int(plan_request_seg_included_count),
            "planRequestSegCharsTotal": int(plan_request_seg_chars_total),
            "planContextEventsPresent": int(plan_context_events_present),
            "planContextLines": int(plan_context_lines),
            "planContextSchemaOk": int(plan_context_lines > 0 and plan_context_schema_ok == plan_context_lines),
            "planCtxUsedTrueCount": int(plan_ctx_used_true_count),
            "planSegCoverageP90": round(float(_percentile_float(plan_seg_coverages, 90)), 6),
            "planPovCoverageP90": round(float(_percentile_float(plan_pov_coverages, 90)), 6),
            "planContextPackPresent": int(plan_context_pack_present),
            "planContextPackLines": int(plan_context_pack_lines),
            "planContextPackSchemaOk": int(
                plan_context_pack_lines > 0 and plan_context_pack_schema_ok == plan_context_pack_lines
            ),
            "planCtxTruncRate": round(
                float(
                    plan_context_pack_trunc_dropped_total
                    / max(1.0, sum(plan_context_pack_chars) + float(plan_context_pack_trunc_dropped_total))
                ),
                6,
            ),
            "planCtxCharsP90": round(float(_percentile_float(plan_context_pack_chars, 90)), 6),
            "frameE2eEventsPresent": int(frame_e2e_events_present),
            "frameE2eSchemaOk": int(frame_e2e_lines > 0 and frame_e2e_schema_ok == frame_e2e_lines),
            "frameE2eCount": int(frame_e2e_lines),
            "frameE2eTotalMsP90": round(float(_percentile_float(frame_e2e_total_ms_values, 90)), 6),
            "frameE2ePartsMissingCount": int(frame_e2e_parts_missing_count),
            "frameE2eDuplicateCount": int(frame_e2e_duplicate_count),
            "frameE2ePartsSumGtTotalCount": int(frame_e2e_parts_sum_gt_total_count),
            "frameInputEventsPresent": int(frame_input_events_present),
            "frameInputLines": int(frame_input_lines),
            "frameInputSchemaOk": int(frame_input_lines > 0 and frame_input_schema_ok == frame_input_lines),
            "frameAckEventsPresent": int(frame_ack_events_present),
            "frameAckLines": int(frame_ack_lines),
            "frameAckSchemaOk": int(frame_ack_lines > 0 and frame_ack_schema_ok == frame_ack_lines),
            "frameAckKindsPresent": int(len(frame_ack_kinds_present)),
            "frameAckTtsCount": int(frame_ack_tts_count),
            "frameAckArCount": int(frame_ack_ar_count),
            "frameAckHapticCount": int(frame_ack_haptic_count),
            "frameUserE2eEventsPresent": int(frame_user_e2e_events_present),
            "frameUserE2eLines": int(frame_user_e2e_lines),
            "frameUserE2eSchemaOk": int(frame_user_e2e_lines > 0 and frame_user_e2e_schema_ok == frame_user_e2e_lines),
            "frameUserE2eNegativeCount": int(frame_user_e2e_negative_count),
            "frameUserE2eDuplicateCount": int(frame_user_e2e_duplicate_count),
            "hazardUnknownKinds": len(hazard_unknown_kinds),
            "hazardAliasHits": int(hazard_alias_hits),
            "riskEventMissingFrameSeq": int(risk_event_missing_frame_seq),
            "riskEventFrameSeqOutOfRange": int(risk_event_frame_seq_out_of_range),
        }

        if not quiet:
            print(f"run package: {run_package}")
            print(f"sourceType: {source_type}")
            print(f"framesDeclared: {frames_count_declared}")
            print(f"framesActual: {frame_count_actual}")
            print(f"normalizedEvents: {summary['normalizedEvents']}")
            print(f"droppedEvents: {summary['droppedEvents']}")
            print(f"eventsV1Present: {events_v1_present}")
            print(f"eventsV1Lines: {events_v1_lines}")
            print(f"eventsV1SchemaOk: {events_v1_schema_ok}")
            print(f"eventsV1Normalized: {events_v1_normalized}")
            print(f"povIrPresent: {summary['povIrPresent']}")
            print(f"povIrSchemaOk: {summary['povIrSchemaOk']}")
            print(f"povIrDecisions: {summary['povIrDecisions']}")
            print(f"povEventsCount: {summary['povEventsCount']}")
            print(f"povConsistencyWarnings: {summary['povConsistencyWarnings']}")
            print(f"segEventsPresent: {summary['segEventsPresent']}")
            print(f"segLines: {summary['segLines']}")
            print(f"segSchemaOk: {summary['segSchemaOk']}")
            print(f"segPayloadSchemaOk: {summary['segPayloadSchemaOk']}")
            print(f"segNormalized: {summary['segNormalized']}")
            print(f"segWarningsCount: {summary['segWarningsCount']}")
            print(f"segPromptEventsPresent: {summary['segPromptEventsPresent']}")
            print(f"segPromptLines: {summary['segPromptLines']}")
            print(f"segPromptSchemaOk: {summary['segPromptSchemaOk']}")
            print(f"segPromptPayloadSchemaOk: {summary['segPromptPayloadSchemaOk']}")
            print(f"segPromptWarningsCount: {summary['segPromptWarningsCount']}")
            print(f"segPromptBudgetPresent: {summary['segPromptBudgetPresent']}")
            print(f"segPromptTruncationPresent: {summary['segPromptTruncationPresent']}")
            print(f"segPromptOutPresent: {summary['segPromptOutPresent']}")
            print(f"segPromptPackedTrueCount: {summary['segPromptPackedTrueCount']}")
            print(f"segBboxOutOfRangeCount: {summary['segBboxOutOfRangeCount']}")
            print(f"segScoreOutOfRangeCount: {summary['segScoreOutOfRangeCount']}")
            print(f"segEmptyLabelCount: {summary['segEmptyLabelCount']}")
            print(f"segMaskPresent: {summary['segMaskPresent']}")
            print(f"segMaskSchemaOk: {summary['segMaskSchemaOk']}")
            print(f"segMaskSizeMismatchCount: {summary['segMaskSizeMismatchCount']}")
            print(f"segMaskBadCountsCount: {summary['segMaskBadCountsCount']}")
            print(f"segContextPresent: {summary['segContextPresent']}")
            print(f"segContextSchemaOk: {summary['segContextSchemaOk']}")
            print(f"segContextChars: {summary['segContextChars']}")
            print(f"segContextSegmentsOut: {summary['segContextSegmentsOut']}")
            print(f"segContextTruncSegmentsDropped: {summary['segContextTruncSegmentsDropped']}")
            print(f"depthEventsPresent: {summary['depthEventsPresent']}")
            print(f"depthLines: {summary['depthLines']}")
            print(f"depthSchemaOk: {summary['depthSchemaOk']}")
            print(f"depthPayloadSchemaOk: {summary['depthPayloadSchemaOk']}")
            print(f"depthNormalized: {summary['depthNormalized']}")
            print(f"depthGridPresentCount: {summary['depthGridPresentCount']}")
            print(f"depthGridBadSizeCount: {summary['depthGridBadSizeCount']}")
            print(f"depthGridOutOfRangeCount: {summary['depthGridOutOfRangeCount']}")
            print(f"planRequestEventsPresent: {summary['planRequestEventsPresent']}")
            print(f"planRequestLines: {summary['planRequestLines']}")
            print(f"planRequestSchemaOk: {summary['planRequestSchemaOk']}")
            print(f"planRequestSegIncludedCount: {summary['planRequestSegIncludedCount']}")
            print(f"planRequestSegCharsTotal: {summary['planRequestSegCharsTotal']}")
            print(f"planContextEventsPresent: {summary['planContextEventsPresent']}")
            print(f"planContextLines: {summary['planContextLines']}")
            print(f"planContextSchemaOk: {summary['planContextSchemaOk']}")
            print(f"planCtxUsedTrueCount: {summary['planCtxUsedTrueCount']}")
            print(f"planSegCoverageP90: {summary['planSegCoverageP90']}")
            print(f"planPovCoverageP90: {summary['planPovCoverageP90']}")
            print(f"planContextPackPresent: {summary['planContextPackPresent']}")
            print(f"planContextPackLines: {summary['planContextPackLines']}")
            print(f"planContextPackSchemaOk: {summary['planContextPackSchemaOk']}")
            print(f"planCtxTruncRate: {summary['planCtxTruncRate']}")
            print(f"planCtxCharsP90: {summary['planCtxCharsP90']}")
            print(f"frameE2eEventsPresent: {summary['frameE2eEventsPresent']}")
            print(f"frameE2eSchemaOk: {summary['frameE2eSchemaOk']}")
            print(f"frameE2eCount: {summary['frameE2eCount']}")
            print(f"frameE2eTotalMsP90: {summary['frameE2eTotalMsP90']}")
            print(f"frameE2ePartsMissingCount: {summary['frameE2ePartsMissingCount']}")
            print(f"frameE2eDuplicateCount: {summary['frameE2eDuplicateCount']}")
            print(f"frameE2ePartsSumGtTotalCount: {summary['frameE2ePartsSumGtTotalCount']}")
            print(f"frameInputEventsPresent: {summary['frameInputEventsPresent']}")
            print(f"frameInputLines: {summary['frameInputLines']}")
            print(f"frameInputSchemaOk: {summary['frameInputSchemaOk']}")
            print(f"frameAckEventsPresent: {summary['frameAckEventsPresent']}")
            print(f"frameAckLines: {summary['frameAckLines']}")
            print(f"frameAckSchemaOk: {summary['frameAckSchemaOk']}")
            print(f"frameAckKindsPresent: {summary['frameAckKindsPresent']}")
            print(f"frameAckTtsCount: {summary['frameAckTtsCount']}")
            print(f"frameAckArCount: {summary['frameAckArCount']}")
            print(f"frameAckHapticCount: {summary['frameAckHapticCount']}")
            print(f"frameUserE2eEventsPresent: {summary['frameUserE2eEventsPresent']}")
            print(f"frameUserE2eLines: {summary['frameUserE2eLines']}")
            print(f"frameUserE2eSchemaOk: {summary['frameUserE2eSchemaOk']}")
            print(f"frameUserE2eNegativeCount: {summary['frameUserE2eNegativeCount']}")
            print(f"frameUserE2eDuplicateCount: {summary['frameUserE2eDuplicateCount']}")
            print(f"hazardUnknownKinds: {summary['hazardUnknownKinds']}")
            print(f"hazardAliasHits: {summary['hazardAliasHits']}")
            print(f"riskEventMissingFrameSeq: {summary['riskEventMissingFrameSeq']}")
            print(f"riskEventFrameSeqOutOfRange: {summary['riskEventFrameSeqOutOfRange']}")
            print(f"warnings: {summary['warningsCount']}")
            print(f"errors: {summary['errorsCount']}")
            print(f"shaChecked: {sha_checked}")
            print(f"shaMismatch: {sha_mismatch}")

            if warnings:
                print("warningSamples:")
                for item in warnings[:10]:
                    print(f"- {item}")
            if errors:
                print("errorSamples:")
                for item in errors[:10]:
                    print(f"- {item}")

        exit_code = 0
        if strict and errors:
            exit_code = 1
        return exit_code, summary
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint BYES run package for basic integrity and schema normalization rate.")
    parser.add_argument("--run-package", required=True)
    parser.add_argument("--strict", action="store_true", default=False)
    args = parser.parse_args()

    run_package = Path(args.run_package)
    try:
        code, _ = lint_run_package(run_package, strict=bool(args.strict))
        return code
    except Exception as exc:  # noqa: BLE001
        print(f"lint failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
