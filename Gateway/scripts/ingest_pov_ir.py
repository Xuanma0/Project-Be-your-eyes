from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent

import sys

if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.schemas.pov_ir_schema import validate_pov_ir  # noqa: E402

_SHA_LINE_RE = re.compile(r"^([a-fA-F0-9]{64})\s+\*?(.+)$")


def ingest_pov_ir(
    *,
    run_package: Path,
    pov_ir_path: Path,
    strict: bool,
    dry_run: bool,
) -> tuple[dict[str, Any], int]:
    warnings: list[str] = []
    infos: list[str] = []
    errors: list[str] = []

    if not run_package.exists() or not run_package.is_dir():
        raise FileNotFoundError(f"run package dir not found: {run_package}")
    if not pov_ir_path.exists() or not pov_ir_path.is_file():
        raise FileNotFoundError(f"pov ir json not found: {pov_ir_path}")

    manifest_path, manifest = _load_manifest(run_package)
    pov_obj = json.loads(pov_ir_path.read_text(encoding="utf-8-sig"))
    if not isinstance(pov_obj, dict):
        raise ValueError("pov ir payload must be json object")

    schema_ok, schema_errors = validate_pov_ir(pov_obj, strict=True)
    if not schema_ok:
        if strict:
            errors.extend(schema_errors)
        else:
            warnings.extend(schema_errors)

    run_id = str(pov_obj.get("runId", "")).strip() or _guess_run_id_from_manifest(manifest) or "pov-ingest"
    events_rel = str(manifest.get("eventsV1Jsonl", "")).strip() or "events/events_v1.jsonl"
    events_path = run_package / events_rel
    pov_rel = "pov/pov_ir_v1.json"
    pov_out_path = run_package / pov_rel

    decisions = _ensure_object_list(pov_obj.get("decisionPoints"))
    events = _ensure_object_list(pov_obj.get("events"))
    highlights = _ensure_object_list(pov_obj.get("highlights"))
    tokens = _ensure_object_list(pov_obj.get("tokens"))

    emitted_rows: list[dict[str, Any]] = []
    frame_seq = 1

    for row in decisions:
        ts_ms = _extract_ts_ms(row, ("t0Ms", "tMs", "tsMs"))
        emitted_rows.append(
            _build_event_row(
                run_id=run_id,
                frame_seq=frame_seq,
                ts_ms=ts_ms,
                name="pov.decision",
                payload=row,
            )
        )
        frame_seq += 1

    for row in events:
        ts_ms = _extract_ts_ms(row, ("tMs", "t0Ms", "tsMs"))
        emitted_rows.append(
            _build_event_row(
                run_id=run_id,
                frame_seq=frame_seq,
                ts_ms=ts_ms,
                name="pov.event",
                payload=row,
            )
        )
        frame_seq += 1

    for row in highlights:
        ts_ms = _extract_ts_ms(row, ("tMs", "t0Ms", "tsMs"))
        emitted_rows.append(
            _build_event_row(
                run_id=run_id,
                frame_seq=frame_seq,
                ts_ms=ts_ms,
                name="pov.highlight",
                payload=row,
            )
        )
        frame_seq += 1

    for row in tokens:
        ts_ms = _extract_ts_ms(row, ("tMs", "t0Ms", "tsMs"))
        emitted_rows.append(
            _build_event_row(
                run_id=run_id,
                frame_seq=frame_seq,
                ts_ms=ts_ms,
                name="pov.token",
                payload=_sanitize_token_payload(row),
            )
        )
        frame_seq += 1

    lines_appended = len(emitted_rows)
    sha_updates: list[dict[str, Any]] = []
    sha_manifest_found = False

    if not errors:
        if not dry_run:
            events_path.parent.mkdir(parents=True, exist_ok=True)
            with events_path.open("a", encoding="utf-8") as fp:
                for row in emitted_rows:
                    fp.write(json.dumps(row, ensure_ascii=False) + "\n")

            pov_out_path.parent.mkdir(parents=True, exist_ok=True)
            if pov_ir_path.resolve() != pov_out_path.resolve():
                shutil.copy2(pov_ir_path, pov_out_path)

            manifest["povIrJson"] = pov_rel
            manifest.setdefault("eventsV1Jsonl", events_rel)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            updates = {
                _to_posix_relative(manifest_path.relative_to(run_package)): _sha256_file(manifest_path),
                _to_posix_relative(events_path.relative_to(run_package)): _sha256_file(events_path),
                _to_posix_relative(pov_out_path.relative_to(run_package)): _sha256_file(pov_out_path),
            }
            sha_files = _discover_sha_lists(run_package)
            sha_manifest_found = bool(sha_files)
            if not sha_manifest_found:
                infos.append("sha manifest not found (skipped)")
            for sha_file in sha_files:
                changed, fmt = _update_sha_manifest(sha_file, updates)
                sha_updates.append({"file": sha_file.name, "updated": changed, "format": fmt})
        else:
            warnings.append("dry-run mode: no files written")

    summary = {
        "source": str(pov_ir_path),
        "runPackage": str(run_package),
        "strict": 1 if strict else 0,
        "dryRun": 1 if dry_run else 0,
        "written": {
            "povIrJson": pov_rel,
            "eventsV1Jsonl": events_rel,
            "eventsLinesAppended": lines_appended,
        },
        "counts": {
            "decisions": len(decisions),
            "events": len(events),
            "highlights": len(highlights),
            "tokens": len(tokens),
        },
        "infos": infos,
        "warnings": warnings,
        "errors": errors,
        "shaManifestFound": sha_manifest_found,
        "shaUpdates": sha_updates,
    }
    exit_code = 1 if errors else 0
    return summary, exit_code


def _build_event_row(
    *,
    run_id: str,
    frame_seq: int,
    ts_ms: int,
    name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": "byes.event.v1",
        "tsMs": int(max(0, ts_ms)),
        "runId": str(run_id or "pov-ingest"),
        "frameSeq": int(max(1, frame_seq)),
        "component": "pov-compiler",
        "category": "pov",
        "name": str(name),
        "phase": "result",
        "status": "ok",
        "latencyMs": None,
        "payload": payload,
    }


def _sanitize_token_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    text = payload.get("text")
    if not isinstance(text, str):
        return payload
    if len(text) <= 120:
        return payload
    payload["text"] = text[:120]
    payload["textLength"] = len(text)
    return payload


def _extract_ts_ms(row: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        value = _to_int(row.get(key))
        if value is not None and value >= 0:
            return int(value)
    return 0


def _ensure_object_list(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def _guess_run_id_from_manifest(manifest: dict[str, Any]) -> str:
    for key in ("runId", "sessionId", "scenarioTag"):
        text = str(manifest.get(key, "")).strip()
        if text:
            return text
    return ""


def _load_manifest(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("manifest must be json object")
        return path, payload
    raise FileNotFoundError(f"manifest not found under: {run_dir}")


def _to_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(float(value))
    except Exception:
        return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _discover_sha_lists(run_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for item in run_dir.iterdir():
        if not item.is_file():
            continue
        lower = item.name.lower()
        if "sha256" in lower or "hash" in lower or lower.endswith(".sha256"):
            candidates.append(item)
    return sorted(candidates)


def _update_json_sha_payload(payload: Any, updates: dict[str, str]) -> tuple[Any, bool]:
    changed = False
    if isinstance(payload, dict):
        files = payload.get("files")
        if isinstance(files, list):
            updated_files, file_changed = _update_json_file_rows(files, updates)
            if file_changed:
                payload = dict(payload)
                payload["files"] = updated_files
                changed = True
            return payload, changed
        if payload and all(isinstance(k, str) and isinstance(v, str) for k, v in payload.items()):
            mapped = dict(payload)
            for rel, sha in updates.items():
                if mapped.get(rel) != sha:
                    mapped[rel] = sha
                    changed = True
            return mapped, changed
    if isinstance(payload, list):
        return _update_json_file_rows(payload, updates)
    return payload, False


def _update_json_file_rows(rows: list[Any], updates: dict[str, str]) -> tuple[list[Any], bool]:
    changed = False
    out: list[Any] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        path_key = "path" if "path" in row else "file" if "file" in row else None
        hash_key = "sha256" if "sha256" in row else "hash" if "hash" in row else None
        if not path_key or not hash_key:
            out.append(row)
            continue
        rel = _to_posix_relative(str(row.get(path_key, "")))
        if rel in updates:
            seen.add(rel)
            sha = updates[rel]
            if str(row.get(hash_key, "")) != sha:
                new_row = dict(row)
                new_row[hash_key] = sha
                out.append(new_row)
                changed = True
            else:
                out.append(row)
        else:
            out.append(row)
    for rel, sha in updates.items():
        if rel not in seen:
            out.append({"path": rel, "sha256": sha})
            changed = True
    return out, changed


def _update_text_sha_lines(text: str, updates: dict[str, str]) -> tuple[str, bool]:
    changed = False
    seen: set[str] = set()
    out_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        m = _SHA_LINE_RE.match(line.strip())
        if not m:
            out_lines.append(line)
            continue
        rel = _to_posix_relative(m.group(2))
        if rel in updates:
            sha = updates[rel]
            seen.add(rel)
            new_line = f"{sha}  {rel}"
            if new_line != line:
                changed = True
            out_lines.append(new_line)
        else:
            out_lines.append(line)
    for rel, sha in updates.items():
        if rel not in seen:
            out_lines.append(f"{sha}  {rel}")
            changed = True
    out_text = "\n".join(out_lines)
    if out_lines:
        out_text += "\n"
    return out_text, changed


def _update_sha_manifest(path: Path, updates: dict[str, str]) -> tuple[bool, str]:
    original = path.read_text(encoding="utf-8-sig")
    try:
        payload = json.loads(original)
    except Exception:
        payload = None
    if payload is not None:
        updated_payload, changed = _update_json_sha_payload(payload, updates)
        if changed:
            path.write_text(json.dumps(updated_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return True, "json"
        return False, "json_no_change"
    updated_text, changed = _update_text_sha_lines(original, updates)
    if changed:
        path.write_text(updated_text, encoding="utf-8")
        return True, "text"
    return False, "text_no_change"


def _to_posix_relative(path: Any) -> str:
    return str(path).replace("\\", "/")


def _print_summary(summary: dict[str, Any]) -> None:
    errors = summary.get("errors", [])
    warnings = summary.get("warnings", [])
    infos = summary.get("infos", [])
    written = summary.get("written", {})
    counts = summary.get("counts", {})
    print(f"source: {summary.get('source', '')}")
    print(f"run-package: {summary.get('runPackage', '')}")
    print(f"strict: {summary.get('strict', 1)}")
    print(f"dry-run: {summary.get('dryRun', 0)}")
    print("written:")
    print(f"  - {written.get('povIrJson', 'pov/pov_ir_v1.json')}")
    print(
        f"  - {written.get('eventsV1Jsonl', 'events/events_v1.jsonl')} "
        f"(appended {int(written.get('eventsLinesAppended', 0) or 0)} lines)"
    )
    print("counts:")
    print(
        "  decisions={decisions}, events={events}, highlights={highlights}, tokens={tokens}".format(
            decisions=int(counts.get("decisions", 0) or 0),
            events=int(counts.get("events", 0) or 0),
            highlights=int(counts.get("highlights", 0) or 0),
            tokens=int(counts.get("tokens", 0) or 0),
        )
    )
    print(f"infos: {len(infos)}")
    print(f"warnings: {len(warnings)}")
    print(f"errors: {1 if errors else 0}")
    if infos:
        for item in infos[:10]:
            print(f"- info: {item}")
    if warnings:
        for item in warnings[:10]:
            print(f"- warning: {item}")
    if errors:
        for item in errors:
            print(f"- error: {item}")


def _parse_bool01(raw: str) -> bool:
    text = str(raw).strip().lower()
    return text in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest POV IR v1 JSON into run package events_v1.")
    parser.add_argument("--run-package", required=True, help="Run package directory path")
    parser.add_argument("--pov-ir", required=True, help="Path to pov_ir.json")
    parser.add_argument("--strict", default="1", help="1: schema failure exits non-zero; 0: warning only")
    parser.add_argument("--dry-run", default="0", help="1: no file writes")
    args = parser.parse_args(argv)

    try:
        summary, exit_code = ingest_pov_ir(
            run_package=Path(args.run_package),
            pov_ir_path=Path(args.pov_ir),
            strict=_parse_bool01(args.strict),
            dry_run=_parse_bool01(args.dry_run),
        )
        _print_summary(summary)
        return int(exit_code)
    except Exception as exc:  # noqa: BLE001
        print(f"ingest failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
