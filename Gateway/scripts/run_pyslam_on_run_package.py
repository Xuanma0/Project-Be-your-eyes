from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent

if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))


class RunPackageHandle:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.run_dir: Path | None = None
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._is_zip = False

    def __enter__(self) -> "RunPackageHandle":
        if self.source.is_dir():
            self.run_dir = self.source
            return self

        if self.source.is_file() and self.source.suffix.lower() == ".zip":
            self._is_zip = True
            self._temp_dir = tempfile.TemporaryDirectory(prefix="byes_runpkg_zip_")
            extract_root = Path(self._temp_dir.name)
            with zipfile.ZipFile(self.source, "r") as zf:
                zf.extractall(extract_root)
            self.run_dir = _discover_run_dir(extract_root)
            return self

        raise FileNotFoundError(f"run package not found: {self.source}")

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()

    @property
    def is_zip(self) -> bool:
        return bool(self._is_zip)

    def commit(self) -> None:
        if not self._is_zip:
            return
        if self.run_dir is None:
            raise RuntimeError("run package not opened")

        tmp_zip = self.source.with_suffix(self.source.suffix + ".tmp")
        if tmp_zip.exists():
            tmp_zip.unlink()
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(self.run_dir.rglob("*")):
                if not path.is_file():
                    continue
                arcname = path.relative_to(self.run_dir).as_posix()
                zf.write(path, arcname)
        tmp_zip.replace(self.source)


def _discover_run_dir(root: Path) -> Path:
    if (root / "manifest.json").exists() or (root / "run_manifest.json").exists():
        return root
    candidates: list[Path] = []
    for name in ("manifest.json", "run_manifest.json"):
        for item in root.rglob(name):
            candidates.append(item.parent)
    if not candidates:
        raise FileNotFoundError(f"manifest not found in extracted zip: {root}")
    candidates = sorted(set(candidates), key=lambda p: len(p.parts))
    return candidates[0]


def _load_manifest(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            return path, payload
    raise FileNotFoundError(f"manifest.json not found under {run_dir}")


def _count_frames(run_dir: Path, manifest: dict[str, Any]) -> int:
    frames_rel = str(manifest.get("framesDir", "")).strip() or "frames"
    frames_dir = run_dir / frames_rel
    if not frames_dir.exists() or not frames_dir.is_dir():
        return 0
    count = 0
    for path in frames_dir.iterdir():
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            count += 1
    return count


def _to_wsl_path(path: Path) -> str:
    raw = str(path.resolve())
    if ":" in raw[:3]:
        drive = raw[0].lower()
        rest = raw[2:].replace("\\", "/")
        if not rest.startswith("/"):
            rest = "/" + rest
        return f"/mnt/{drive}{rest}"
    return raw.replace("\\", "/")


def _select_pyslam_fixture_dir(run_dir: Path) -> Path | None:
    candidates = [run_dir / "gt" / "pyslam_fixture", run_dir / "pyslam_fixture"]
    for item in candidates:
        if item.exists() and item.is_dir():
            return item
    return None


def _run_fixture_mode(
    *,
    run_dir: Path,
    out_dir: Path,
    save_online: bool,
    save_final: bool,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    written: list[str] = []
    fixture_dir = _select_pyslam_fixture_dir(run_dir)
    if fixture_dir is None:
        warnings.append("pyslam_fixture directory not found (checked gt/pyslam_fixture and pyslam_fixture)")
        return written, warnings

    sources: list[tuple[str, bool]] = [
        ("byes_traj_online.txt", save_online),
        ("byes_traj_final.txt", save_final),
    ]
    for filename, enabled in sources:
        if not enabled:
            continue
        src = fixture_dir / filename
        if not src.exists() or not src.is_file():
            warnings.append(f"fixture trajectory missing: {src}")
            continue
        dst = out_dir / filename
        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        written.append(str(dst))
    if not written:
        warnings.append("no trajectory file copied from fixture")
    return written, warnings


@dataclass
class WslRunResult:
    exit_code: int
    written_files: list[str]
    warnings: list[str]
    stdout: str


def _run_wsl_mode(
    *,
    run_dir: Path,
    out_dir: Path,
    dry_run: bool,
    wsl_distro: str,
    pyslam_root: str,
    config: str,
    save_online: bool,
    save_final: bool,
) -> WslRunResult:
    warnings: list[str] = []
    if dry_run:
        return WslRunResult(exit_code=0, written_files=[], warnings=["dry-run"], stdout="")
    if not pyslam_root:
        return WslRunResult(exit_code=1, written_files=[], warnings=["missing --pyslam-root or PYSLAM_ROOT"], stdout="")

    pyslam_root_path = Path(pyslam_root).expanduser().resolve()
    if not pyslam_root_path.exists() or not pyslam_root_path.is_dir():
        return WslRunResult(exit_code=1, written_files=[], warnings=[f"pyslam_root not found: {pyslam_root_path}"], stdout="")

    config_path = Path(config).expanduser().resolve() if config else (pyslam_root_path / "config.yaml")
    if not config_path.exists() or not config_path.is_file():
        return WslRunResult(exit_code=1, written_files=[], warnings=[f"config not found: {config_path}"], stdout="")

    frames_dir = run_dir / "frames"
    if not frames_dir.exists() or not frames_dir.is_dir():
        return WslRunResult(exit_code=1, written_files=[], warnings=[f"frames dir not found: {frames_dir}"], stdout="")

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "pyslam.log"
    online_path = out_dir / "byes_traj_online.txt"
    final_path = out_dir / "byes_traj_final.txt"
    patched_config = out_dir / "config_byes.yaml"

    config_text = config_path.read_text(encoding="utf-8-sig")
    # Keep patching minimal: append overrides so local users can quickly adapt.
    config_text += (
        "\n\n# BYES v4.73 overrides (auto-generated)\n"
        "DATASET:\n"
        "  type: FOLDER_DATASET\n"
        "FOLDER_DATASET:\n"
        "  sensor_type: mono\n"
        f"  base_path: \"{_to_wsl_path(frames_dir)}\"\n"
        "SAVE_TRAJECTORY:\n"
        "  save_trajectory: True\n"
        "  format_type: tum\n"
        f"  output_folder: \"{_to_wsl_path(out_dir)}\"\n"
        "  basename: byes_traj\n"
    )
    patched_config.write_text(config_text, encoding="utf-8")

    cmd = (
        f"cd '{_to_wsl_path(pyslam_root_path)}' && "
        f"python3 ./main_slam.py --config '{_to_wsl_path(patched_config)}'"
    )
    proc = subprocess.run(  # noqa: S603
        ["wsl.exe", "-d", str(wsl_distro), "--", "bash", "-lc", cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    combined_out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    log_path.write_text(combined_out, encoding="utf-8")

    written: list[str] = []
    if save_online and online_path.exists() and online_path.is_file():
        written.append(str(online_path))
    if save_final and final_path.exists() and final_path.is_file():
        written.append(str(final_path))
    if save_online and str(online_path) not in written:
        warnings.append(f"missing expected output: {online_path}")
    if save_final and str(final_path) not in written:
        warnings.append(f"missing expected output: {final_path}")

    return WslRunResult(exit_code=int(proc.returncode or 0), written_files=written, warnings=warnings, stdout=combined_out)


def run_pyslam_on_run_package(
    *,
    run_package_path: Path,
    out_dir_raw: str,
    mode: str,
    wsl_distro: str,
    pyslam_root: str,
    config: str,
    save_online: bool,
    save_final: bool,
    dry_run: bool,
) -> tuple[dict[str, Any], int]:
    with RunPackageHandle(run_package_path) as handle:
        run_dir = handle.run_dir
        if run_dir is None:
            raise RuntimeError("run package open failed")
        _, manifest = _load_manifest(run_dir)
        run_id = str(manifest.get("runId", "")).strip() or run_dir.name
        out_dir = Path(out_dir_raw).resolve() if str(out_dir_raw or "").strip() else (run_dir / "pyslam")

        warnings: list[str] = []
        written_files: list[str] = []
        exit_code = 0
        wsl_stdout = ""
        mode_lower = str(mode or "fixture").strip().lower()
        if mode_lower == "fixture":
            written_files, warnings = _run_fixture_mode(
                run_dir=run_dir,
                out_dir=out_dir,
                save_online=save_online,
                save_final=save_final,
                dry_run=dry_run,
            )
        elif mode_lower == "wsl":
            result = _run_wsl_mode(
                run_dir=run_dir,
                out_dir=out_dir,
                dry_run=dry_run,
                wsl_distro=wsl_distro,
                pyslam_root=pyslam_root,
                config=config,
                save_online=save_online,
                save_final=save_final,
            )
            exit_code = int(result.exit_code)
            written_files = list(result.written_files)
            warnings.extend(result.warnings)
            wsl_stdout = result.stdout
        else:
            raise ValueError(f"unsupported mode: {mode}")

        summary_path = out_dir / "run_summary.json"
        summary = {
            "schemaVersion": "byes.pyslam.run.summary.v1",
            "runPackage": str(run_package_path),
            "runId": run_id,
            "mode": mode_lower,
            "outDir": str(out_dir),
            "framesCount": int(_count_frames(run_dir, manifest)),
            "filesWritten": written_files,
            "warnings": warnings,
            "exitCode": int(exit_code),
            "wslDistro": str(wsl_distro or ""),
            "pyslamRoot": str(pyslam_root or ""),
            "config": str(config or ""),
            "dryRun": bool(dry_run),
        }
        if wsl_stdout:
            summary["stdoutTail"] = wsl_stdout[-2000:]
        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if handle.is_zip:
                handle.commit()
        return summary, exit_code


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pySLAM over a run package and emit TUM trajectories")
    parser.add_argument("--run-package", required=True, help="run package dir or zip")
    parser.add_argument("--out-dir", default="", help="output dir for trajectories (default: <runpkg>/pyslam)")
    parser.add_argument("--mode", default="fixture", choices=["fixture", "wsl"], help="fixture (CI) or wsl (local)")
    parser.add_argument("--wsl-distro", default="Ubuntu", help="WSL distro for mode=wsl")
    parser.add_argument("--pyslam-root", default="", help="pySLAM root path (default from PYSLAM_ROOT env)")
    parser.add_argument("--config", default="", help="optional pySLAM config path")
    parser.add_argument("--save-online", type=int, default=1, help="write byes_traj_online.txt (1/0)")
    parser.add_argument("--save-final", type=int, default=1, help="write byes_traj_final.txt (1/0)")
    parser.add_argument("--dry-run", action="store_true", help="prepare only, do not write files")
    return parser.parse_args()


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"run-package: {summary.get('runPackage')}")
    print(f"run-id: {summary.get('runId')}")
    print(f"mode: {summary.get('mode')}")
    print(f"out-dir: {summary.get('outDir')}")
    print(f"frames-count: {summary.get('framesCount')}")
    files = summary.get("filesWritten")
    files = files if isinstance(files, list) else []
    print(f"files-written: {len(files)}")
    for path in files:
        print(f"  - {path}")
    warnings = summary.get("warnings")
    warnings = warnings if isinstance(warnings, list) else []
    print(f"warnings: {len(warnings)}")
    for item in warnings[:10]:
        print(f"  - {item}")
    print(f"exit-code: {summary.get('exitCode')}")


def main() -> int:
    args = _parse_args()
    pyslam_root = str(args.pyslam_root or "").strip() or str(os.environ.get("PYSLAM_ROOT", "")).strip()
    summary, exit_code = run_pyslam_on_run_package(
        run_package_path=Path(args.run_package).resolve(),
        out_dir_raw=str(args.out_dir or "").strip(),
        mode=str(args.mode or "fixture"),
        wsl_distro=str(args.wsl_distro or "Ubuntu"),
        pyslam_root=pyslam_root,
        config=str(args.config or "").strip(),
        save_online=bool(int(args.save_online)),
        save_final=bool(int(args.save_final)),
        dry_run=bool(args.dry_run),
    )
    _print_summary(summary)
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
