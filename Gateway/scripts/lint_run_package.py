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

from byes.event_normalizer import collect_normalized_ws_events

_SHA_LINE_RE = re.compile(r"^([a-fA-F0-9]{64})\s+\*?(.+)$")


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


def lint_run_package(run_package: Path, strict: bool = False) -> tuple[int, dict[str, Any]]:
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

        frame_files = sorted(frames_dir.glob("frame_*.jpg")) if frames_dir.exists() else []
        frame_count_actual = len(frame_files)
        if frames_count_declared > 0 and frame_count_actual != frames_count_declared:
            warnings.append(
                f"frames count mismatch declared={frames_count_declared} actual={frame_count_actual}"
            )

        gt = manifest.get("groundTruth")
        gt_covered = 0
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

        ws_rel = str(manifest.get("wsJsonl", "ws_events.jsonl") or "ws_events.jsonl")
        ws_path = run_root / ws_rel
        if not ws_path.exists():
            errors.append(f"ws jsonl missing: {ws_rel}")
            norm = {"normalizedEvents": 0, "droppedEvents": 0, "warningsCount": 0}
        else:
            norm = collect_normalized_ws_events(ws_path)
            warnings.extend(norm.get("warnings", []))

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
        }

        print(f"run package: {run_package}")
        print(f"sourceType: {source_type}")
        print(f"framesDeclared: {frames_count_declared}")
        print(f"framesActual: {frame_count_actual}")
        print(f"normalizedEvents: {summary['normalizedEvents']}")
        print(f"droppedEvents: {summary['droppedEvents']}")
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
