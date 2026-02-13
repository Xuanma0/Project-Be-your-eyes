from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

_SHA_LINE_RE = re.compile(r"^([a-fA-F0-9]{64})\s+\*?(.+)$")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def _zip_dir(source_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(source_dir.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(source_dir))


def _load_manifest(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_dir / name
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("manifest must be a json object")
            return path, payload
    raise FileNotFoundError(f"manifest not found under: {run_dir}")


def _update_manifest_ground_truth(
    manifest: dict[str, Any],
    *,
    has_ocr: bool,
    has_risk: bool,
    match_window_frames: int,
) -> None:
    gt = manifest.get("groundTruth")
    if not isinstance(gt, dict):
        gt = {}
    gt["version"] = 1
    if has_ocr:
        gt["ocrJsonl"] = "ground_truth/ocr.jsonl"
    if has_risk:
        gt["riskJsonl"] = "ground_truth/depth_risk.jsonl"
    gt["matchWindowFrames"] = max(0, int(match_window_frames))
    manifest["groundTruth"] = gt


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
            # path -> sha map
            mapped = dict(payload)
            for rel, sha in updates.items():
                if rel in mapped and mapped[rel] != sha:
                    mapped[rel] = sha
                    changed = True
            for rel, sha in updates.items():
                if rel not in mapped:
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
        if path_key is None or hash_key is None:
            out.append(row)
            continue

        rel = str(row.get(path_key, "")).replace("\\", "/")
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
        rel = m.group(2).replace("\\", "/")
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


def _prepare_workdir(input_path: Path) -> tuple[Path, bool, Path | None]:
    if input_path.is_dir():
        return input_path, False, None
    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        temp_root = Path(tempfile.mkdtemp(prefix="attach_gt_"))
        _safe_extract_zip(input_path, temp_root)
        return temp_root, True, temp_root
    raise FileNotFoundError(f"run package not found: {input_path}")


def _ensure_run_root(extracted_root: Path) -> Path:
    if (extracted_root / "manifest.json").exists() or (extracted_root / "run_manifest.json").exists():
        return extracted_root
    candidates = [p.parent for p in extracted_root.rglob("manifest.json")]
    if not candidates:
        candidates = [p.parent for p in extracted_root.rglob("run_manifest.json")]
    if not candidates:
        raise FileNotFoundError("manifest not found in extracted package")
    candidates.sort(key=lambda p: len(str(p)))
    return candidates[0]


def _copy_gt_file(src: Path, dst: Path, overwrite: bool) -> bool:
    if dst.exists() and not overwrite:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def attach_ground_truth(
    *,
    run_package: Path,
    ocr_path: Path | None,
    risk_path: Path | None,
    match_window_frames: int,
    out: Path | None,
    overwrite: bool,
) -> dict[str, Any]:
    if ocr_path is None and risk_path is None:
        raise ValueError("at least one of --ocr or --risk is required")

    source_kind = "dir" if run_package.is_dir() else "zip"
    work_root, input_is_zip, cleanup_dir = _prepare_workdir(run_package)
    try:
        run_root = _ensure_run_root(work_root)

        # when dir input + out provided, work on a copied root instead of in-place
        if not input_is_zip and out is not None:
            if out.suffix.lower() == ".zip":
                temp_copy = Path(tempfile.mkdtemp(prefix="attach_gt_copy_"))
                shutil.copytree(run_root, temp_copy, dirs_exist_ok=True)
                run_root = temp_copy
                if cleanup_dir is None:
                    cleanup_dir = temp_copy
            else:
                if out.exists() and not overwrite:
                    raise FileExistsError(f"output already exists: {out}")
                if out.exists():
                    shutil.rmtree(out)
                shutil.copytree(run_root, out)
                run_root = out

        manifest_path, manifest = _load_manifest(run_root)

        written_files: list[str] = []
        gt_dir = run_root / "ground_truth"
        if ocr_path is not None:
            if _copy_gt_file(ocr_path, gt_dir / "ocr.jsonl", overwrite=overwrite):
                written_files.append("ground_truth/ocr.jsonl")
        if risk_path is not None:
            if _copy_gt_file(risk_path, gt_dir / "depth_risk.jsonl", overwrite=overwrite):
                written_files.append("ground_truth/depth_risk.jsonl")

        _update_manifest_ground_truth(
            manifest,
            has_ocr=ocr_path is not None,
            has_risk=risk_path is not None,
            match_window_frames=match_window_frames,
        )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        updates: dict[str, str] = {
            "manifest.json" if manifest_path.name == "manifest.json" else "run_manifest.json": _sha256_file(manifest_path)
        }
        if (gt_dir / "ocr.jsonl").exists():
            updates["ground_truth/ocr.jsonl"] = _sha256_file(gt_dir / "ocr.jsonl")
        if (gt_dir / "depth_risk.jsonl").exists():
            updates["ground_truth/depth_risk.jsonl"] = _sha256_file(gt_dir / "depth_risk.jsonl")

        sha_files = _discover_sha_lists(run_root)
        sha_updates: list[dict[str, Any]] = []
        for sha_file in sha_files:
            changed, fmt = _update_sha_manifest(sha_file, updates)
            sha_updates.append({"file": sha_file.name, "updated": changed, "format": fmt})

        # also keep manifest export.files (if present) aligned
        export_block = manifest.get("export")
        if isinstance(export_block, dict) and isinstance(export_block.get("files"), list):
            updated_files, changed = _update_json_file_rows(list(export_block["files"]), updates)
            if changed:
                manifest = dict(manifest)
                export_block = dict(export_block)
                export_block["files"] = updated_files
                manifest["export"] = export_block
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        out_path: Path
        if input_is_zip:
            if out is None:
                out_path = run_package.with_name(f"{run_package.stem}_gt.zip")
            else:
                out_path = out
            _zip_dir(run_root, out_path)
        elif out is None:
            out_path = run_root
        elif out.suffix.lower() == ".zip":
            out_path = out
            _zip_dir(run_root, out_path)
        else:
            out_path = run_root

        return {
            "sourceType": source_kind,
            "runPackage": str(run_package),
            "out": str(out_path),
            "writtenGtFiles": written_files,
            "manifestUpdated": True,
            "shaUpdates": sha_updates,
            "shaManifestFound": bool(sha_files),
        }
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"source type: {summary.get('sourceType')}")
    print(f"run package: {summary.get('runPackage')}")
    print(f"out: {summary.get('out')}")
    files = summary.get("writtenGtFiles", [])
    print("written GT files:")
    if files:
        for item in files:
            print(f"- {item}")
    else:
        print("- (none)")
    print(f"manifest updated: {summary.get('manifestUpdated')}")
    if summary.get("shaManifestFound"):
        print("sha256 manifest updates:")
        for item in summary.get("shaUpdates", []):
            print(f"- {item.get('file')}: updated={item.get('updated')} format={item.get('format')}")
    else:
        print("sha256 manifest updates: not found (skipped)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach optional GT jsonl files into a run package directory or zip.")
    parser.add_argument("--run-package", required=True)
    parser.add_argument("--ocr", default=None)
    parser.add_argument("--risk", default=None)
    parser.add_argument("--match-window-frames", type=int, default=2)
    parser.add_argument("--out", default=None)
    parser.add_argument("--overwrite", action="store_true", default=False)
    args = parser.parse_args()

    run_package = Path(args.run_package)
    ocr_path = Path(args.ocr) if args.ocr else None
    risk_path = Path(args.risk) if args.risk else None
    out_path = Path(args.out) if args.out else None

    if ocr_path is not None and not ocr_path.exists():
        print(f"ocr gt file not found: {ocr_path}")
        return 1
    if risk_path is not None and not risk_path.exists():
        print(f"risk gt file not found: {risk_path}")
        return 1

    try:
        summary = attach_ground_truth(
            run_package=run_package,
            ocr_path=ocr_path,
            risk_path=risk_path,
            match_window_frames=args.match_window_frames,
            out=out_path,
            overwrite=bool(args.overwrite),
        )
        _print_summary(summary)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"attach failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
