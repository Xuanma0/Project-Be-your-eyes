from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

try:
    import requests
except Exception:  # noqa: BLE001
    requests = None  # type: ignore[assignment]


def _default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[1] / "external" / "modelpack" / "manifest.yaml"


def _parse_models_arg(raw: str) -> list[str]:
    value = str(raw or "").strip().lower()
    if value in {"", "all", "*"}:
        return []
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a YAML object")
    models = payload.get("models")
    if not isinstance(models, dict):
        raise ValueError("manifest.models must be an object")
    return payload


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _download_to(url: str, output: Path, expected_sha256: str | None) -> None:
    _ensure_parent(output)
    tmp_path = output.with_suffix(output.suffix + ".part")
    sha = hashlib.sha256()
    if requests is not None:
        with requests.get(url, stream=True, timeout=60) as resp:  # type: ignore[union-attr]
            resp.raise_for_status()
            with tmp_path.open("wb") as fp:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    if not chunk:
                        continue
                    fp.write(chunk)
                    sha.update(chunk)
    else:
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
            with tmp_path.open("wb") as fp:
                while True:
                    chunk = resp.read(1024 * 64)
                    if not chunk:
                        break
                    fp.write(chunk)
                    sha.update(chunk)

    actual_sha = sha.hexdigest()
    if expected_sha256:
        expected = expected_sha256.strip().lower()
        if expected and actual_sha != expected:
            tmp_path.unlink(missing_ok=True)
            raise ValueError(f"sha256 mismatch: expected={expected}, actual={actual_sha}")

    tmp_path.replace(output)


def _write_placeholder(path: Path, *, model_name: str, model_id: str, backend: str) -> None:
    _ensure_parent(path)
    if path.exists():
        return
    content = "\n".join(
        [
            "# Placeholder weights file",
            f"model={model_name}",
            f"model_id={model_id}",
            f"backend={backend}",
            "status=not_downloaded",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _resolve_output_path(entry: dict[str, Any], *, out_dir: Path, model_id: str) -> Path:
    file_name_raw = str(entry.get("file_name", "")).strip()
    if not file_name_raw:
        weights_path_raw = str(entry.get("weights_path", "")).strip()
        if weights_path_raw:
            file_name_raw = Path(weights_path_raw).name
    if not file_name_raw:
        file_name_raw = "model.bin"
    file_name = Path(file_name_raw).name
    return out_dir / model_id / file_name


def run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    out_dir = Path(args.out_dir).resolve()
    selected = set(_parse_models_arg(args.models))

    if not manifest_path.exists():
        print(f"[ERROR] Manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    try:
        manifest = _load_manifest(manifest_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to parse manifest: {exc}", file=sys.stderr)
        return 2

    models = manifest.get("models", {})
    model_names = sorted(models.keys())
    if selected:
        unknown = sorted(selected.difference(model_names))
        if unknown:
            print(f"[ERROR] Unknown model key(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        targets = [name for name in model_names if name in selected]
    else:
        targets = model_names

    print(f"[INFO] Manifest: {manifest_path}")
    print(f"[INFO] Output dir: {out_dir}")
    print(f"[INFO] Targets: {', '.join(targets)}")

    failures = 0
    for name in targets:
        entry = models.get(name, {})
        if not isinstance(entry, dict):
            print(f"[WARN] Skip invalid manifest entry: {name}")
            continue

        model_id = str(entry.get("model_id", f"byes-{name}-unknown")).strip()
        backend = str(entry.get("backend", "mock")).strip()
        url = entry.get("url")
        sha256 = entry.get("sha256")
        license_note = entry.get("license_note")
        input_size = entry.get("input_size")
        output_format = entry.get("output_format")
        weights_path_raw = str(entry.get("weights_path", "")).strip()
        full_path = _resolve_output_path(entry, out_dir=out_dir, model_id=model_id)

        print(f"[INFO] {name}: model_id={model_id}, backend={backend}, path={full_path}")
        if weights_path_raw:
            print(f"[INFO] {name}: manifest weights_path={weights_path_raw}")
        if input_size is not None:
            print(f"[INFO] {name}: input_size={input_size}")
        if output_format is not None:
            print(f"[INFO] {name}: output_format={output_format}")
        if license_note:
            print(f"[INFO] {name}: license_note={license_note}")

        has_url = isinstance(url, str) and bool(url.strip())
        if has_url:
            try:
                _download_to(str(url).strip(), full_path, str(sha256) if sha256 else None)
                print(f"[OK] Downloaded: {name} -> {full_path}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"[ERROR] Download failed for {name}: {exc}", file=sys.stderr)
                continue
        else:
            _write_placeholder(full_path, model_name=name, model_id=model_id, backend=backend)
            print(f"[WARN] {name}: 未配置下载源(url)，已创建占位文件: {full_path}")

    if failures > 0:
        print(f"[ERROR] pull_models finished with {failures} failure(s)", file=sys.stderr)
        return 1
    print("[OK] pull_models finished")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pull model artifacts for BeYourEyes Gateway modelpack.")
    parser.add_argument(
        "--manifest",
        default=str(_default_manifest_path()),
        help="Path to manifest.yaml",
    )
    parser.add_argument(
        "--models",
        default="det,ocr,depth,vlm",
        help='Comma list, e.g. "det,ocr" or "all"',
    )
    parser.add_argument(
        "--out-dir",
        default=str((_default_manifest_path().parent / "weights").resolve()),
        help="BYES_WEIGHTS_DIR root output. Files are placed under <out-dir>/<model_id>/",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
