from __future__ import annotations

import argparse
import json
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
from byes.schemas.pov_ir_schema import validate_pov_ir

_SHA_LINE_RE = re.compile(r"^([a-fA-F0-9]{64})\s+\*?(.+)$")
_SEG_SCHEMA_PATH = GATEWAY_ROOT / "contracts" / "byes.seg.v1.json"


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


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _validate_seg_payload(payload: dict[str, Any], schema: dict[str, Any] | None) -> tuple[bool, int, int, int]:
    payload_ok = True
    bbox_out_of_range = 0
    score_out_of_range = 0
    empty_label = 0

    if schema is not None and jsonschema is not None:
        try:
            jsonschema.validate(payload, schema)
        except Exception:
            payload_ok = False

    segments_raw = payload.get("segments")
    if not isinstance(segments_raw, list):
        return False, bbox_out_of_range, score_out_of_range, empty_label

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

    return payload_ok, bbox_out_of_range, score_out_of_range, empty_label


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
        seg_payload_schema_ok = 0
        seg_bbox_out_of_range_count = 0
        seg_score_out_of_range_count = 0
        seg_empty_label_count = 0
        seg_schema = _load_seg_contract_schema()
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
                                    payload_ok, bbox_oor, score_oor, empty_label = _validate_seg_payload(payload, seg_schema)
                                    if payload_ok:
                                        seg_payload_schema_ok += 1
                                    else:
                                        seg_warnings_count += 1
                                    seg_bbox_out_of_range_count += int(bbox_oor)
                                    seg_score_out_of_range_count += int(score_oor)
                                    seg_empty_label_count += int(empty_label)
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
            "segBboxOutOfRangeCount": int(seg_bbox_out_of_range_count),
            "segScoreOutOfRangeCount": int(seg_score_out_of_range_count),
            "segEmptyLabelCount": int(seg_empty_label_count),
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
            print(f"segBboxOutOfRangeCount: {summary['segBboxOutOfRangeCount']}")
            print(f"segScoreOutOfRangeCount: {summary['segScoreOutOfRangeCount']}")
            print(f"segEmptyLabelCount: {summary['segEmptyLabelCount']}")
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
