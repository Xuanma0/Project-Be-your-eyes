from __future__ import annotations

import argparse
import json
import math
import shutil
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


@dataclass
class TumPoseRow:
    line_no: int
    ts_raw: str
    ts_ms: int | None
    tx: float
    ty: float
    tz: float
    qx: float
    qy: float
    qz: float
    qw: float


@dataclass
class MatchedPose:
    row: TumPoseRow
    frame_seq: int
    event_ts_ms: int
    warnings_count: int


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


def ingest_pyslam_tum(
    *,
    run_package_path: Path,
    tum_path: Path,
    run_id_override: str | None,
    tolerance_ms: int,
    dry_run: bool,
) -> tuple[dict[str, Any], int]:
    warnings: list[str] = []
    if not tum_path.exists() or not tum_path.is_file():
        raise FileNotFoundError(f"tum trajectory not found: {tum_path}")

    with RunPackageHandle(run_package_path) as handle:
        run_dir = handle.run_dir
        if run_dir is None:
            raise RuntimeError("run package open failed")

        manifest_path, manifest = _load_manifest(run_dir)
        run_id = str(run_id_override or "").strip() or _guess_run_id(manifest) or "pyslam-ingest"
        events_rel = str(manifest.get("eventsV1Jsonl", "")).strip() or "events/events_v1.jsonl"
        events_path = run_dir / events_rel

        tum_rows, invalid_lines = _parse_tum_file(tum_path)
        frame_seqs, frame_ts_by_seq, frame_index_warnings = _load_frame_index(run_dir, manifest)
        warnings.extend(frame_index_warnings)

        if not tum_rows:
            summary = {
                "source": str(tum_path),
                "runPackage": str(run_package_path),
                "runId": run_id,
                "matched": 0,
                "unmatched": 0,
                "invalid_lines": invalid_lines,
                "written": 0,
                "warnings": warnings,
                "out_path": str(events_path),
            }
            return summary, 0

        matched_rows: list[MatchedPose] = []
        unmatched = 0
        mode = "timestamp"

        if frame_ts_by_seq:
            matched_rows, unmatched, used_offset = _match_by_timestamp(
                tum_rows=tum_rows,
                frame_ts_by_seq=frame_ts_by_seq,
                tolerance_ms=max(0, int(tolerance_ms)),
            )
            if used_offset:
                warnings.append("applied timestamp offset alignment (tum relative time -> frame timeline)")
            if not matched_rows:
                matched_rows, unmatched = _match_by_order(tum_rows=tum_rows, frame_seqs=frame_seqs, frame_ts_by_seq=frame_ts_by_seq)
                mode = "index-fallback"
                warnings.append("timestamp matching produced 0 matches, fallback to frame-index mapping")
        else:
            matched_rows, unmatched = _match_by_order(tum_rows=tum_rows, frame_seqs=frame_seqs, frame_ts_by_seq=frame_ts_by_seq)
            mode = "index-fallback"
            warnings.append("no usable frame timestamps found, fallback to frame-index mapping")

        event_rows = _build_event_rows(run_id=run_id, matched_rows=matched_rows)

        if not dry_run:
            events_path.parent.mkdir(parents=True, exist_ok=True)
            with events_path.open("a", encoding="utf-8") as fp:
                for row in event_rows:
                    fp.write(json.dumps(row, ensure_ascii=False) + "\n")
            if handle.is_zip:
                handle.commit()

        summary = {
            "source": str(tum_path),
            "runPackage": str(run_package_path),
            "runId": run_id,
            "mode": mode,
            "matched": len(matched_rows),
            "unmatched": unmatched,
            "invalid_lines": invalid_lines,
            "warnings": warnings,
            "written": 0 if dry_run else len(event_rows),
            "dryRun": bool(dry_run),
            "out_path": str(events_path),
        }
        return summary, 0


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


def _parse_tum_file(path: Path) -> tuple[list[TumPoseRow], int]:
    rows: list[TumPoseRow] = []
    invalid = 0
    with path.open("r", encoding="utf-8-sig") as fp:
        for idx, raw in enumerate(fp, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 8:
                invalid += 1
                continue
            ts_text = parts[0]
            try:
                ts_float = float(ts_text)
                ts_ms = _tum_ts_to_ms(ts_float)
                tx, ty, tz, qx, qy, qz, qw = (float(v) for v in parts[1:8])
            except Exception:
                invalid += 1
                continue
            rows.append(
                TumPoseRow(
                    line_no=idx,
                    ts_raw=ts_text,
                    ts_ms=ts_ms,
                    tx=tx,
                    ty=ty,
                    tz=tz,
                    qx=qx,
                    qy=qy,
                    qz=qz,
                    qw=qw,
                )
            )
    return rows, invalid


def _tum_ts_to_ms(ts_value: float) -> int | None:
    if not math.isfinite(ts_value):
        return None
    abs_val = abs(ts_value)
    if abs_val >= 1e14:
        return int(round(ts_value / 1_000_000.0))
    if abs_val >= 1e11:
        return int(round(ts_value))
    return int(round(ts_value * 1000.0))


def _match_by_timestamp(
    *,
    tum_rows: list[TumPoseRow],
    frame_ts_by_seq: dict[int, int],
    tolerance_ms: int,
) -> tuple[list[MatchedPose], int, bool]:
    frame_items = sorted(frame_ts_by_seq.items(), key=lambda item: item[0])
    matched, unmatched = _do_timestamp_match(
        tum_rows=tum_rows,
        frame_items=frame_items,
        tolerance_ms=tolerance_ms,
        offset_ms=0,
    )
    if matched:
        return matched, unmatched, False

    if not tum_rows or not frame_items:
        return matched, unmatched, False
    first_ts = tum_rows[0].ts_ms
    first_frame_ts = frame_items[0][1]
    if first_ts is None:
        return matched, unmatched, False

    # Common pySLAM/TUM case: timestamp is relative (seconds from start).
    offset_ms = int(first_frame_ts - first_ts)
    adjusted, adjusted_unmatched = _do_timestamp_match(
        tum_rows=tum_rows,
        frame_items=frame_items,
        tolerance_ms=tolerance_ms,
        offset_ms=offset_ms,
    )
    if adjusted:
        return adjusted, adjusted_unmatched, True
    return matched, unmatched, False


def _do_timestamp_match(
    *,
    tum_rows: list[TumPoseRow],
    frame_items: list[tuple[int, int]],
    tolerance_ms: int,
    offset_ms: int,
) -> tuple[list[MatchedPose], int]:
    matched: list[MatchedPose] = []
    unmatched = 0
    tol = max(0, int(tolerance_ms))
    for row in tum_rows:
        if row.ts_ms is None:
            unmatched += 1
            continue
        target_ts = int(row.ts_ms + offset_ms)
        best_seq: int | None = None
        best_frame_ts: int | None = None
        best_diff: int | None = None
        for seq, frame_ts in frame_items:
            diff = abs(int(frame_ts) - target_ts)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_seq = int(seq)
                best_frame_ts = int(frame_ts)
        if best_seq is None or best_frame_ts is None or best_diff is None or best_diff > tol:
            unmatched += 1
            continue
        matched.append(
            MatchedPose(
                row=row,
                frame_seq=best_seq,
                event_ts_ms=best_frame_ts,
                warnings_count=0,
            )
        )
    return matched, unmatched


def _match_by_order(
    *,
    tum_rows: list[TumPoseRow],
    frame_seqs: list[int],
    frame_ts_by_seq: dict[int, int],
) -> tuple[list[MatchedPose], int]:
    matched: list[MatchedPose] = []
    unmatched = 0
    if not frame_seqs:
        return matched, len(tum_rows)

    auto_ts = 0
    for idx, row in enumerate(tum_rows):
        if idx >= len(frame_seqs):
            unmatched += 1
            continue
        seq = int(frame_seqs[idx])
        frame_ts = frame_ts_by_seq.get(seq)
        if frame_ts is not None:
            ts_ms = int(frame_ts)
        elif row.ts_ms is not None:
            ts_ms = int(row.ts_ms)
        else:
            auto_ts += 33
            ts_ms = auto_ts
        matched.append(
            MatchedPose(
                row=row,
                frame_seq=seq,
                event_ts_ms=max(0, int(ts_ms)),
                warnings_count=1,
            )
        )
    return matched, unmatched


def _build_event_rows(*, run_id: str, matched_rows: list[MatchedPose]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for matched in matched_rows:
        row = matched.row
        warnings_count = max(0, int(matched.warnings_count))
        payload = {
            "schemaVersion": "byes.slam_pose.v1",
            "runId": str(run_id),
            "frameSeq": int(matched.frame_seq),
            "backend": "offline",
            "model": "pyslam",
            "endpoint": "",
            "trackingState": "tracking",
            "pose": {
                "t": [float(row.tx), float(row.ty), float(row.tz)],
                "q": [float(row.qx), float(row.qy), float(row.qz), float(row.qw)],
                "frame": "world_to_cam",
            },
            "warningsCount": warnings_count,
        }
        rows.append(
            {
                "schemaVersion": "byes.event.v1",
                "tsMs": int(max(0, matched.event_ts_ms)),
                "runId": str(run_id),
                "frameSeq": int(matched.frame_seq),
                "component": "gateway",
                "category": "tool",
                "name": "slam.pose",
                "phase": "result",
                "status": "ok",
                "latencyMs": None,
                "payload": payload,
            }
        )
    return rows


def _load_manifest(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            return path, payload
    raise FileNotFoundError(f"manifest not found under run package: {run_dir}")


def _guess_run_id(manifest: dict[str, Any]) -> str:
    for key in ("runId", "sessionId", "scenarioTag"):
        text = str(manifest.get(key, "")).strip()
        if text:
            return text
    return ""


def _load_frame_index(run_dir: Path, manifest: dict[str, Any]) -> tuple[list[int], dict[int, int], list[str]]:
    warnings: list[str] = []
    frame_seqs: list[int] = []
    frame_ts_by_seq: dict[int, int] = {}

    rel = str(manifest.get("framesMetaJsonl", "")).strip() or "frames_meta.jsonl"
    meta_path = run_dir / rel
    if meta_path.exists():
        with meta_path.open("r", encoding="utf-8-sig") as fp:
            auto_seq = 1
            for raw in fp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                seq = _extract_frame_seq(row)
                if seq is None:
                    seq = auto_seq
                auto_seq += 1
                frame_seqs.append(seq)
                ts = _extract_ts_ms(row)
                if ts is not None:
                    frame_ts_by_seq[seq] = ts
    else:
        warnings.append(f"frames meta missing: {rel}")

    if not frame_seqs:
        frames_rel = str(manifest.get("framesDir", "")).strip() or "frames"
        frames_dir = run_dir / frames_rel
        if frames_dir.exists():
            files = sorted([path for path in frames_dir.iterdir() if path.is_file()])
            frame_seqs = list(range(1, len(files) + 1))
        else:
            warnings.append(f"frames directory missing: {frames_rel}")

    frame_seqs = sorted({int(seq) for seq in frame_seqs if isinstance(seq, int) and seq > 0})
    return frame_seqs, frame_ts_by_seq, warnings


def _extract_frame_seq(row: dict[str, Any]) -> int | None:
    for key in ("frameSeq", "seq", "frame", "index"):
        value = _to_int(row.get(key))
        if value is not None and value > 0:
            return value
    nested = row.get("meta")
    if isinstance(nested, dict):
        for key in ("frameSeq", "seq", "frame"):
            value = _to_int(nested.get(key))
            if value is not None and value > 0:
                return value
    return None


def _extract_ts_ms(row: dict[str, Any]) -> int | None:
    for key in ("captureTsMs", "tsMs", "timestampMs", "timeMs", "recvTsMs", "tMs", "ts"):
        value = _to_int(row.get(key))
        if value is not None and value >= 0:
            return value
    meta = row.get("meta")
    if isinstance(meta, dict):
        for key in ("captureTsMs", "tsMs", "timestampMs", "timeMs", "recvTsMs", "tMs", "ts"):
            value = _to_int(meta.get(key))
            if value is not None and value >= 0:
                return value
    return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(float(value))
    except Exception:
        return None


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"source: {summary.get('source')}")
    print(f"run-package: {summary.get('runPackage')}")
    print(f"run-id: {summary.get('runId')}")
    print(f"mode: {summary.get('mode')}")
    print(f"written: {summary.get('written')}")
    print(f"matched: {summary.get('matched')}")
    print(f"unmatched: {summary.get('unmatched')}")
    print(f"invalid_lines: {summary.get('invalid_lines')}")
    warnings = summary.get("warnings")
    if isinstance(warnings, list):
        print(f"warnings: {len(warnings)}")
        for item in warnings[:8]:
            print(f"  - {item}")
    print(f"out_path: {summary.get('out_path')}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest pySLAM TUM trajectory into run-package slam.pose events")
    parser.add_argument("--run-package", required=True, help="run package directory or .zip")
    parser.add_argument("--tum", required=True, help="trajectory file in TUM format")
    parser.add_argument("--run-id", default="", help="optional run id override for emitted events")
    parser.add_argument("--tolerance-ms", type=int, default=50, help="timestamp nearest-neighbor tolerance in ms")
    parser.add_argument("--dry-run", action="store_true", help="parse and match only, do not write files")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary, exit_code = ingest_pyslam_tum(
        run_package_path=Path(args.run_package).resolve(),
        tum_path=Path(args.tum).resolve(),
        run_id_override=str(args.run_id or "").strip() or None,
        tolerance_ms=int(args.tolerance_ms),
        dry_run=bool(args.dry_run),
    )
    _print_summary(summary)
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
