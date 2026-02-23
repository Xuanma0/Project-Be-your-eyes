from __future__ import annotations

import argparse
import json
import math
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
    ts_value: float
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
    residual_ms: int | None = None
    target_ts_ms: int | None = None


@dataclass
class TumTrajectory:
    path: Path
    label: str
    rows: list[TumPoseRow]
    invalid_lines: int
    time_base: str
    time_unit: str


@dataclass
class AlignmentDiagnostics:
    mode: str
    matched: int
    unmatched: int
    residual_values_ms: list[int]
    a: float | None = None
    b: float | None = None


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
    tum_paths: list[Path],
    run_id_override: str | None,
    tolerance_ms: int,
    align_mode: str,
    traj_label: str,
    tum_time_base: str,
    tum_time_unit: str,
    dry_run: bool,
) -> tuple[dict[str, Any], int]:
    warnings: list[str] = []
    resolved_tum_paths = [path for path in tum_paths if path.exists() and path.is_file()]
    if not resolved_tum_paths:
        raise FileNotFoundError("no valid TUM trajectories found")

    with RunPackageHandle(run_package_path) as handle:
        run_dir = handle.run_dir
        if run_dir is None:
            raise RuntimeError("run package open failed")

        manifest_path, manifest = _load_manifest(run_dir)
        run_id = str(run_id_override or "").strip() or _guess_run_id(manifest) or "pyslam-ingest"
        events_rel = str(manifest.get("eventsV1Jsonl", "")).strip() or "events/events_v1.jsonl"
        events_path = run_dir / events_rel

        frame_seqs, frame_ts_by_seq, frame_index_warnings = _load_frame_index(run_dir, manifest)
        warnings.extend(frame_index_warnings)
        frames_count = len(frame_seqs)

        all_event_rows: list[dict[str, Any]] = []
        per_traj_results: list[dict[str, Any]] = []
        matched_total = 0
        unmatched_total = 0
        invalid_total = 0
        tum_count_total = 0
        residual_values_all: list[int] = []
        mode_counter: dict[str, int] = {}
        align_a: float | None = None
        align_b: float | None = None
        time_base_detected: str | None = None
        time_unit_detected: str | None = None

        for tum_path in resolved_tum_paths:
            label = _resolve_traj_label(tum_path, traj_label)
            trajectory = _parse_tum_file(
                tum_path,
                time_base=tum_time_base,
                time_unit=tum_time_unit,
            )
            tum_count_total += len(trajectory.rows)
            invalid_total += int(trajectory.invalid_lines)
            if time_base_detected is None:
                time_base_detected = trajectory.time_base
            if time_unit_detected is None:
                time_unit_detected = trajectory.time_unit
            if not trajectory.rows:
                per_traj_results.append(
                    {
                        "path": str(tum_path),
                        "label": label,
                        "alignModeUsed": "none",
                        "tumCount": 0,
                        "matched": 0,
                        "unmatched": 0,
                    }
                )
                continue

            diagnostics, matched_rows = _align_tum_rows(
                rows=trajectory.rows,
                frame_seqs=frame_seqs,
                frame_ts_by_seq=frame_ts_by_seq,
                tolerance_ms=max(0, int(tolerance_ms)),
                align_mode=align_mode,
                warnings=warnings,
            )
            matched_count = int(diagnostics.matched)
            unmatched_count = int(diagnostics.unmatched)
            matched_total += matched_count
            unmatched_total += unmatched_count
            residual_values_all.extend(diagnostics.residual_values_ms)
            mode_counter[diagnostics.mode] = mode_counter.get(diagnostics.mode, 0) + 1
            if diagnostics.a is not None:
                align_a = diagnostics.a
            if diagnostics.b is not None:
                align_b = diagnostics.b
            per_traj_results.append(
                {
                    "path": str(tum_path),
                    "label": label,
                    "alignModeUsed": diagnostics.mode,
                    "tumCount": len(trajectory.rows),
                    "matched": matched_count,
                    "unmatched": unmatched_count,
                }
            )
            all_event_rows.extend(_build_event_rows(run_id=run_id, matched_rows=matched_rows, model_label=label))

        mode_used = max(mode_counter, key=mode_counter.get) if mode_counter else "none"
        residual_stats = _summarize_residual_ms(residual_values_all)
        ingest_summary = {
            "schemaVersion": "byes.slam.ingest.summary.v1",
            "runId": run_id,
            "alignModeUsed": mode_used,
            "a": _round_float(align_a),
            "b": _round_float(align_b),
            "tumCount": int(tum_count_total),
            "framesCount": int(frames_count),
            "matched": int(matched_total),
            "unmatched": int(unmatched_total),
            "invalidLines": int(invalid_total),
            "timeBaseDetected": time_base_detected or "unknown",
            "timeUnitDetected": time_unit_detected or "unknown",
            "residualMs": residual_stats,
            "warningsCount": int(len(warnings)),
            "trajectories": per_traj_results,
        }
        ingest_summary_path = events_path.parent / "slam_ingest_summary.json"

        if not dry_run:
            events_path.parent.mkdir(parents=True, exist_ok=True)
            with events_path.open("a", encoding="utf-8") as fp:
                for row in all_event_rows:
                    fp.write(json.dumps(row, ensure_ascii=False) + "\n")
            ingest_summary_path.write_text(json.dumps(ingest_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if handle.is_zip:
                handle.commit()

        summary = {
            "source": [str(path) for path in resolved_tum_paths],
            "runPackage": str(run_package_path),
            "runId": run_id,
            "mode": mode_used,
            "alignModeUsed": mode_used,
            "a": _round_float(align_a),
            "b": _round_float(align_b),
            "matched": int(matched_total),
            "unmatched": int(unmatched_total),
            "tumCount": int(tum_count_total),
            "framesCount": int(frames_count),
            "invalid_lines": int(invalid_total),
            "residualMs": residual_stats,
            "timeBaseDetected": time_base_detected or "unknown",
            "timeUnitDetected": time_unit_detected or "unknown",
            "trajectories": per_traj_results,
            "warnings": warnings,
            "written": 0 if dry_run else len(all_event_rows),
            "dryRun": bool(dry_run),
            "out_path": str(events_path),
            "ingestSummaryPath": str(ingest_summary_path),
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


def _parse_tum_file(path: Path, *, time_base: str, time_unit: str) -> TumTrajectory:
    parsed_rows: list[tuple[int, str, float, float, float, float, float, float, float]] = []
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
            try:
                ts_float = float(parts[0])
                tx, ty, tz, qx, qy, qz, qw = (float(v) for v in parts[1:8])
            except Exception:
                invalid += 1
                continue
            parsed_rows.append((idx, parts[0], ts_float, tx, ty, tz, qx, qy, qz, qw))

    detected_unit = _detect_tum_time_unit([row[2] for row in parsed_rows], override=time_unit)
    detected_base = _detect_tum_time_base([row[2] for row in parsed_rows], unit=detected_unit, override=time_base)
    rows: list[TumPoseRow] = []
    for line_no, ts_raw, ts_value, tx, ty, tz, qx, qy, qz, qw in parsed_rows:
        ts_ms = _tum_ts_to_ms(ts_value, unit=detected_unit)
        rows.append(
            TumPoseRow(
                line_no=line_no,
                ts_raw=ts_raw,
                ts_value=ts_value,
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
    return TumTrajectory(
        path=path,
        label=_resolve_traj_label(path, "auto"),
        rows=rows,
        invalid_lines=invalid,
        time_base=detected_base,
        time_unit=detected_unit,
    )


def _detect_tum_time_unit(values: list[float], *, override: str) -> str:
    normalized = str(override or "auto").strip().lower()
    if normalized in {"seconds", "milliseconds", "nanoseconds"}:
        return normalized
    finite_values = [abs(v) for v in values if math.isfinite(v)]
    if not finite_values:
        return "seconds"
    max_abs = max(finite_values)
    all_integer_like = all(abs(v - round(v)) < 1e-9 for v in finite_values[: min(len(finite_values), 50)])
    if all_integer_like and max_abs > 1e12:
        return "nanoseconds"
    if all_integer_like and max_abs > 1e9:
        return "milliseconds"
    return "seconds"


def _detect_tum_time_base(values: list[float], *, unit: str, override: str) -> str:
    normalized = str(override or "auto").strip().lower()
    if normalized in {"epoch_seconds", "relative_seconds"}:
        return normalized
    finite_values = [v for v in values if math.isfinite(v)]
    if not finite_values:
        return "epoch_seconds"
    to_seconds = {
        "seconds": 1.0,
        "milliseconds": 1.0 / 1000.0,
        "nanoseconds": 1.0 / 1_000_000_000.0,
    }.get(unit, 1.0)
    max_seconds = max(abs(v) * to_seconds for v in finite_values)
    if max_seconds < 1e8:
        return "relative_seconds"
    return "epoch_seconds"


def _tum_ts_to_ms(ts_value: float, *, unit: str) -> int | None:
    if not math.isfinite(ts_value):
        return None
    if unit == "nanoseconds":
        return int(round(ts_value / 1_000_000.0))
    if unit == "milliseconds":
        return int(round(ts_value))
    return int(round(ts_value * 1000.0))


def _align_tum_rows(
    *,
    rows: list[TumPoseRow],
    frame_seqs: list[int],
    frame_ts_by_seq: dict[int, int],
    tolerance_ms: int,
    align_mode: str,
    warnings: list[str],
) -> tuple[AlignmentDiagnostics, list[MatchedPose]]:
    if not rows:
        return AlignmentDiagnostics(mode="none", matched=0, unmatched=0, residual_values_ms=[]), []
    normalized_mode = str(align_mode or "auto").strip().lower()
    mode_to_use = normalized_mode
    if normalized_mode == "auto":
        frame_count = max(1, len(frame_seqs))
        ratio = float(len(rows)) / float(frame_count)
        if 0.8 <= ratio <= 1.2:
            mode_to_use = "index"
        elif frame_ts_by_seq:
            mode_to_use = "fit_linear"
        else:
            mode_to_use = "index"
            warnings.append("align-mode auto fallback to index: no frame timestamps")

    if mode_to_use == "index":
        matched_rows, unmatched = _match_by_index(rows=rows, frame_seqs=frame_seqs, frame_ts_by_seq=frame_ts_by_seq)
        residual_values = [int(abs(item.residual_ms)) for item in matched_rows if item.residual_ms is not None]
        return AlignmentDiagnostics(mode="index", matched=len(matched_rows), unmatched=unmatched, residual_values_ms=residual_values), matched_rows

    if mode_to_use == "nearest":
        matched_rows, unmatched = _match_by_nearest(
            rows=rows,
            frame_ts_by_seq=frame_ts_by_seq,
            tolerance_ms=tolerance_ms,
        )
        residual_values = [int(abs(item.residual_ms)) for item in matched_rows if item.residual_ms is not None]
        return AlignmentDiagnostics(mode="nearest", matched=len(matched_rows), unmatched=unmatched, residual_values_ms=residual_values), matched_rows

    if mode_to_use == "fit_linear":
        if not frame_ts_by_seq:
            warnings.append("align-mode fit_linear fallback to index: no frame timestamps")
            matched_rows, unmatched = _match_by_index(rows=rows, frame_seqs=frame_seqs, frame_ts_by_seq=frame_ts_by_seq)
            residual_values = [int(abs(item.residual_ms)) for item in matched_rows if item.residual_ms is not None]
            return AlignmentDiagnostics(mode="index-fallback", matched=len(matched_rows), unmatched=unmatched, residual_values_ms=residual_values), matched_rows
        matched_rows, unmatched, a, b = _match_by_fit_linear(
            rows=rows,
            frame_ts_by_seq=frame_ts_by_seq,
            tolerance_ms=tolerance_ms,
        )
        residual_values = [int(abs(item.residual_ms)) for item in matched_rows if item.residual_ms is not None]
        return AlignmentDiagnostics(
            mode="fit_linear",
            matched=len(matched_rows),
            unmatched=unmatched,
            residual_values_ms=residual_values,
            a=a,
            b=b,
        ), matched_rows

    warnings.append(f"unknown align mode '{align_mode}', fallback to index")
    matched_rows, unmatched = _match_by_index(rows=rows, frame_seqs=frame_seqs, frame_ts_by_seq=frame_ts_by_seq)
    residual_values = [int(abs(item.residual_ms)) for item in matched_rows if item.residual_ms is not None]
    return AlignmentDiagnostics(mode="index-fallback", matched=len(matched_rows), unmatched=unmatched, residual_values_ms=residual_values), matched_rows


def _match_by_index(
    *,
    rows: list[TumPoseRow],
    frame_seqs: list[int],
    frame_ts_by_seq: dict[int, int],
) -> tuple[list[MatchedPose], int]:
    matched: list[MatchedPose] = []
    if not frame_seqs:
        return matched, len(rows)
    unmatched = 0
    for idx, row in enumerate(rows):
        if idx >= len(frame_seqs):
            unmatched += 1
            continue
        seq = int(frame_seqs[idx])
        frame_ts = frame_ts_by_seq.get(seq)
        if frame_ts is not None:
            event_ts = int(frame_ts)
            target_ts = int(frame_ts)
            residual = 0
        elif row.ts_ms is not None:
            event_ts = int(row.ts_ms)
            target_ts = int(row.ts_ms)
            residual = 0
        else:
            event_ts = int((idx + 1) * 33)
            target_ts = event_ts
            residual = 0
        matched.append(
            MatchedPose(
                row=row,
                frame_seq=seq,
                event_ts_ms=max(0, event_ts),
                warnings_count=1 if frame_ts is None else 0,
                residual_ms=residual,
                target_ts_ms=target_ts,
            )
        )
    return matched, unmatched


def _match_by_nearest(
    *,
    rows: list[TumPoseRow],
    frame_ts_by_seq: dict[int, int],
    tolerance_ms: int,
) -> tuple[list[MatchedPose], int]:
    matched: list[MatchedPose] = []
    unmatched = 0
    if not frame_ts_by_seq:
        return matched, len(rows)
    frame_items = sorted(frame_ts_by_seq.items(), key=lambda item: item[0])
    used_frames: set[int] = set()
    tol = max(0, int(tolerance_ms))
    first_row_ts = rows[0].ts_ms
    first_frame_ts = frame_items[0][1] if frame_items else None
    offset_ms = int(first_frame_ts - first_row_ts) if first_row_ts is not None and first_frame_ts is not None else 0

    for row in rows:
        if row.ts_ms is None:
            unmatched += 1
            continue
        target_ts = int(row.ts_ms + offset_ms)
        best_seq: int | None = None
        best_ts: int | None = None
        best_diff: int | None = None
        for seq, frame_ts in frame_items:
            if seq in used_frames:
                continue
            diff = abs(int(frame_ts) - target_ts)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_seq = int(seq)
                best_ts = int(frame_ts)
        if best_seq is None or best_ts is None or best_diff is None or best_diff > tol:
            unmatched += 1
            continue
        used_frames.add(best_seq)
        matched.append(
            MatchedPose(
                row=row,
                frame_seq=best_seq,
                event_ts_ms=best_ts,
                warnings_count=0,
                residual_ms=int(best_diff),
                target_ts_ms=target_ts,
            )
        )
    return matched, unmatched


def _match_by_fit_linear(
    *,
    rows: list[TumPoseRow],
    frame_ts_by_seq: dict[int, int],
    tolerance_ms: int,
) -> tuple[list[MatchedPose], int, float, float]:
    matched: list[MatchedPose] = []
    if not frame_ts_by_seq:
        return matched, len(rows), 1.0, 0.0
    frame_items = sorted(frame_ts_by_seq.items(), key=lambda item: item[0])
    x_values = [float(row.ts_ms) for row in rows if row.ts_ms is not None]
    y_values = [float(ts) for _, ts in frame_items]
    sample_count = min(len(x_values), len(y_values))
    if sample_count <= 0:
        return matched, len(rows), 1.0, 0.0
    x_samples = x_values[:sample_count]
    y_samples = y_values[:sample_count]
    a, b = _fit_linear(x_samples, y_samples)
    tol = max(0, int(tolerance_ms))
    used_frames: set[int] = set()
    unmatched = 0
    for row in rows:
        if row.ts_ms is None:
            unmatched += 1
            continue
        predicted = float(a * float(row.ts_ms) + b)
        best_seq: int | None = None
        best_ts: int | None = None
        best_diff: float | None = None
        for seq, frame_ts in frame_items:
            if seq in used_frames:
                continue
            diff = abs(float(frame_ts) - predicted)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_seq = int(seq)
                best_ts = int(frame_ts)
        if best_seq is None or best_ts is None or best_diff is None or best_diff > float(tol):
            unmatched += 1
            continue
        used_frames.add(best_seq)
        matched.append(
            MatchedPose(
                row=row,
                frame_seq=best_seq,
                event_ts_ms=int(best_ts),
                warnings_count=0,
                residual_ms=int(round(best_diff)),
                target_ts_ms=int(round(predicted)),
            )
        )
    return matched, unmatched, a, b


def _fit_linear(x_values: list[float], y_values: list[float]) -> tuple[float, float]:
    n = min(len(x_values), len(y_values))
    if n <= 0:
        return 1.0, 0.0
    sx = sum(x_values[:n])
    sy = sum(y_values[:n])
    sxx = sum(x * x for x in x_values[:n])
    sxy = sum(x * y for x, y in zip(x_values[:n], y_values[:n]))
    denom = float(n) * sxx - sx * sx
    if abs(denom) < 1e-9:
        a = 1.0
        b = (sy / float(n)) - a * (sx / float(n))
        return a, b
    a = (float(n) * sxy - sx * sy) / denom
    b = (sy - a * sx) / float(n)
    return float(a), float(b)


def _build_event_rows(*, run_id: str, matched_rows: list[MatchedPose], model_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    model_name = f"pyslam-{model_label}" if model_label in {"online", "final"} else "pyslam"
    for matched in matched_rows:
        row = matched.row
        warnings_count = max(0, int(matched.warnings_count))
        payload = {
            "schemaVersion": "byes.slam_pose.v1",
            "runId": str(run_id),
            "frameSeq": int(matched.frame_seq),
            "backend": "offline",
            "model": model_name,
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


def _resolve_traj_label(path: Path, traj_label: str) -> str:
    normalized = str(traj_label or "auto").strip().lower()
    if normalized in {"online", "final"}:
        return normalized
    filename = path.name.lower()
    if "final" in filename:
        return "final"
    if "online" in filename:
        return "online"
    return "online"


def _collect_tum_paths(*, tum_paths: list[str], tum_dir: str | None) -> list[Path]:
    collected: list[Path] = []
    for raw in tum_paths:
        text = str(raw or "").strip()
        if not text:
            continue
        collected.append(Path(text).resolve())
    if tum_dir:
        folder = Path(tum_dir).resolve()
        if folder.exists() and folder.is_dir():
            for suffix in ("*.tum", "*.txt"):
                for item in sorted(folder.glob(suffix)):
                    if item.is_file():
                        collected.append(item.resolve())
    unique: list[Path] = []
    seen: set[str] = set()
    for path in collected:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _summarize_residual_ms(values: list[int]) -> dict[str, Any]:
    clean = sorted(int(max(0, v)) for v in values if isinstance(v, int))
    if not clean:
        return {"count": 0, "p50": None, "p90": None, "max": None, "valuesSample": []}
    return {
        "count": len(clean),
        "p50": _percentile(clean, 50),
        "p90": _percentile(clean, 90),
        "max": clean[-1],
        "valuesSample": clean[:10],
    }


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return int(values[0])
    pct_clamped = max(0.0, min(100.0, float(pct)))
    position = (len(values) - 1) * (pct_clamped / 100.0)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return int(values[lower])
    weight = position - float(lower)
    lower_val = float(values[lower])
    upper_val = float(values[upper])
    return int(round(lower_val + (upper_val - lower_val) * weight))


def _round_float(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"source: {summary.get('source')}")
    print(f"run-package: {summary.get('runPackage')}")
    print(f"run-id: {summary.get('runId')}")
    print(f"mode: {summary.get('mode')}")
    print(f"timeBaseDetected: {summary.get('timeBaseDetected')}")
    print(f"timeUnitDetected: {summary.get('timeUnitDetected')}")
    print(f"tumCount: {summary.get('tumCount')}")
    print(f"framesCount: {summary.get('framesCount')}")
    print(f"written: {summary.get('written')}")
    print(f"matched: {summary.get('matched')}")
    print(f"unmatched: {summary.get('unmatched')}")
    print(f"invalid_lines: {summary.get('invalid_lines')}")
    print(f"a: {summary.get('a')}")
    print(f"b: {summary.get('b')}")
    residual = summary.get("residualMs")
    if isinstance(residual, dict):
        print(
            "residualMs: "
            f"count={residual.get('count')} p50={residual.get('p50')} "
            f"p90={residual.get('p90')} max={residual.get('max')}"
        )
    trajectories = summary.get("trajectories")
    if isinstance(trajectories, list):
        print(f"trajectories: {len(trajectories)}")
        for row in trajectories[:8]:
            if not isinstance(row, dict):
                continue
            print(
                "  - "
                f"{row.get('label')} "
                f"matched={row.get('matched')} unmatched={row.get('unmatched')} "
                f"mode={row.get('alignModeUsed')} file={row.get('path')}"
            )
    warnings = summary.get("warnings")
    if isinstance(warnings, list):
        print(f"warnings: {len(warnings)}")
        for item in warnings[:8]:
            print(f"  - {item}")
    print(f"out_path: {summary.get('out_path')}")
    print(f"ingest_summary_path: {summary.get('ingestSummaryPath')}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest pySLAM TUM trajectory into run-package slam.pose events")
    parser.add_argument("--run-package", required=True, help="run package directory or .zip")
    parser.add_argument("--tum", action="append", default=[], help="trajectory file in TUM format (can repeat)")
    parser.add_argument("--tum-dir", default="", help="directory containing TUM trajectories (*.tum/*.txt)")
    parser.add_argument("--traj-label", default="auto", choices=["online", "final", "auto"], help="trajectory label for model field")
    parser.add_argument("--tum-time-base", default="auto", choices=["auto", "epoch_seconds", "relative_seconds"])
    parser.add_argument("--tum-time-unit", default="auto", choices=["auto", "seconds", "milliseconds", "nanoseconds"])
    parser.add_argument("--align-mode", default="auto", choices=["auto", "index", "nearest", "fit_linear"])
    parser.add_argument("--run-id", default="", help="optional run id override for emitted events")
    parser.add_argument("--tolerance-ms", type=int, default=50, help="timestamp nearest-neighbor tolerance in ms")
    parser.add_argument("--dry-run", action="store_true", help="parse and match only, do not write files")
    args = parser.parse_args()
    if not args.tum and not str(args.tum_dir or "").strip():
        parser.error("at least one --tum or --tum-dir is required")
    return args


def main() -> int:
    args = _parse_args()
    tum_paths = _collect_tum_paths(tum_paths=list(args.tum or []), tum_dir=str(args.tum_dir or "").strip() or None)
    if not tum_paths:
        raise SystemExit("no TUM files resolved from --tum/--tum-dir")
    summary, exit_code = ingest_pyslam_tum(
        run_package_path=Path(args.run_package).resolve(),
        tum_paths=tum_paths,
        run_id_override=str(args.run_id or "").strip() or None,
        tolerance_ms=int(args.tolerance_ms),
        align_mode=str(args.align_mode or "auto"),
        traj_label=str(args.traj_label or "auto"),
        tum_time_base=str(args.tum_time_base or "auto"),
        tum_time_unit=str(args.tum_time_unit or "auto"),
        dry_run=bool(args.dry_run),
    )
    _print_summary(summary)
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
