from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe_run_id(raw: str | None, *, fallback_prefix: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return f"{fallback_prefix}_{_utc_now_compact()}"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
    return safe or f"{fallback_prefix}_{_utc_now_compact()}"


def _to_positive_float(raw: Any, default: float) -> float:
    try:
        value = float(raw)
        if value <= 0:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_nonnegative_float(raw: Any, default: float) -> float:
    try:
        value = float(raw)
        if value < 0:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_positive_int(raw: Any, default: int) -> int:
    try:
        value = int(raw)
        if value <= 0:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _write_min_metrics(path: Path, frames_count: int) -> None:
    path.write_text(
        "# TYPE byes_frame_received_total counter\n"
        f"byes_frame_received_total {int(max(0, frames_count))}\n",
        encoding="utf-8",
    )


def _prepare_output_dir(out_dir: Path, overwrite: bool) -> None:
    if out_dir.exists():
        if not overwrite:
            raise FileExistsError(f"output path exists, pass --overwrite: {out_dir}")
        shutil.rmtree(out_dir)
    (out_dir / "frames").mkdir(parents=True, exist_ok=True)
    (out_dir / "events").mkdir(parents=True, exist_ok=True)


def import_ego4d_video(
    *,
    video_path: Path,
    out_dir: Path,
    run_id: str | None,
    fps: float,
    start_sec: float,
    duration_sec: float,
    max_frames: int,
    resize_width: int,
    overwrite: bool,
) -> tuple[dict[str, Any], int]:
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("OpenCV (cv2) is required for video import") from exc

    if not video_path.exists() or not video_path.is_file():
        raise FileNotFoundError(f"video file not found: {video_path}")

    run_id_safe = _safe_run_id(run_id, fallback_prefix="ego4d_import")
    _prepare_output_dir(out_dir, overwrite=overwrite)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    effective_source_fps = source_fps if source_fps > 0 else 30.0
    target_fps = max(0.1, float(fps))
    sample_period = 1.0 / target_fps

    if start_sec > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(start_sec) * 1000.0)

    next_sample_rel_sec = 0.0
    frame_seq = 0
    read_frames = 0
    written_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    first_rel_t_sec: float | None = None
    last_rel_t_sec = 0.0
    video_start_unix_ms = 0
    warnings.append("video_start_unix_ms unavailable, defaulting to 0")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        read_frames += 1

        pos_frames = float(cap.get(cv2.CAP_PROP_POS_FRAMES) or 0.0)
        pos_msec = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
        if pos_msec > 0:
            t_sec = max(0.0, pos_msec / 1000.0)
        else:
            # CAP_PROP_POS_FRAMES is 1-based after successful read on most backends.
            t_sec = max(0.0, (max(0.0, pos_frames - 1.0)) / effective_source_fps)

        if t_sec < start_sec:
            continue

        rel_t_sec = max(0.0, t_sec - start_sec)
        if duration_sec > 0 and rel_t_sec > duration_sec:
            break

        if rel_t_sec + 1e-9 < next_sample_rel_sec:
            continue
        while next_sample_rel_sec <= rel_t_sec:
            next_sample_rel_sec += sample_period

        frame_seq += 1
        if max_frames > 0 and frame_seq > max_frames:
            break

        h, w = frame.shape[:2]
        if resize_width > 0 and w > resize_width:
            scale = float(resize_width) / float(max(1, w))
            new_h = max(1, int(round(h * scale)))
            frame = cv2.resize(frame, (resize_width, new_h), interpolation=cv2.INTER_AREA)
            h, w = frame.shape[:2]

        frame_name = f"frame_{frame_seq:06d}.jpg"
        frame_rel = f"frames/{frame_name}"
        frame_path = out_dir / frame_rel
        ok_write = cv2.imwrite(str(frame_path), frame)
        if not ok_write:
            raise RuntimeError(f"failed to write frame jpeg: {frame_path}")

        capture_ts_ms = int(video_start_unix_ms + round(rel_t_sec * 1000.0))
        source_meta = {
            "type": "ego4d",
            "videoPath": str(video_path),
            "fps": float(target_fps),
            "tSec": float(round(rel_t_sec, 6)),
        }
        row = {
            "frameSeq": int(frame_seq),
            "seq": int(frame_seq),
            "framePath": frame_rel,
            "captureTsMs": int(capture_ts_ms),
            "tsMs": int(capture_ts_ms),
            "source": source_meta,
            "meta": {
                "seq": int(frame_seq),
                "timestampMs": int(capture_ts_ms),
                "captureTsMs": int(capture_ts_ms),
                "width": int(w),
                "height": int(h),
                "source": source_meta,
            },
        }
        written_rows.append(row)
        if first_rel_t_sec is None:
            first_rel_t_sec = rel_t_sec
        last_rel_t_sec = rel_t_sec

        if max_frames > 0 and frame_seq >= max_frames:
            break

    cap.release()

    frames_meta_path = out_dir / "frames_meta.jsonl"
    with frames_meta_path.open("w", encoding="utf-8") as fp:
        for row in written_rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    events_path = out_dir / "events" / "events_v1.jsonl"
    events_path.write_text("", encoding="utf-8")

    metrics_before_path = out_dir / "metrics_before.txt"
    metrics_after_path = out_dir / "metrics_after.txt"
    _write_min_metrics(metrics_before_path, len(written_rows))
    _write_min_metrics(metrics_after_path, len(written_rows))

    manifest = {
        "runId": run_id_safe,
        "scenarioTag": "import_ego4d_video",
        "datasetTag": "ego4d",
        "sourceVideo": str(video_path),
        "fps": float(target_fps),
        "startSec": float(start_sec),
        "durationSec": float(duration_sec if duration_sec > 0 else 0),
        "framesDir": "frames",
        "framesMetaJsonl": "frames_meta.jsonl",
        "eventsV1Jsonl": "events/events_v1.jsonl",
        "wsJsonl": "events/events_v1.jsonl",
        "metricsBefore": "metrics_before.txt",
        "metricsAfter": "metrics_after.txt",
        "framesCount": int(len(written_rows)),
        "frameCountSent": int(len(written_rows)),
        "eventCountAccepted": 0,
        "errors": [],
        "importSummary": {
            "sourceType": "ego4d",
            "videoPath": str(video_path),
            "sourceFps": float(source_fps),
            "targetFps": float(target_fps),
            "readFrames": int(read_frames),
            "warnings": warnings,
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    duration_written = 0.0
    if first_rel_t_sec is not None:
        duration_written = max(0.0, last_rel_t_sec - first_rel_t_sec)
    summary = {
        "framesWritten": int(len(written_rows)),
        "durationSec": float(round(duration_written, 3)),
        "outPath": str(out_dir),
        "runId": run_id_safe,
    }
    return summary, 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import an Ego4D video into BYE run-package format")
    parser.add_argument("--video-path", required=True, help="Path to source video file")
    parser.add_argument("--out", required=True, help="Output run-package directory")
    parser.add_argument("--run-id", default="", help="Optional runId override")
    parser.add_argument("--fps", type=float, default=5.0, help="Sampling FPS")
    parser.add_argument("--start-sec", type=float, default=0.0, help="Start offset in seconds")
    parser.add_argument("--duration-sec", type=float, default=30.0, help="Duration in seconds (<=0 means full)")
    parser.add_argument("--max-frames", type=int, default=300, help="Maximum frames to export (<=0 means unlimited)")
    parser.add_argument("--resize", type=int, default=640, help="Resize width in pixels (<=0 disables resize)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    summary, exit_code = import_ego4d_video(
        video_path=Path(args.video_path).resolve(),
        out_dir=Path(args.out).resolve(),
        run_id=str(args.run_id or "").strip() or None,
        fps=_to_positive_float(args.fps, 5.0),
        start_sec=_to_nonnegative_float(args.start_sec, 0.0),
        duration_sec=float(args.duration_sec),
        max_frames=_to_positive_int(args.max_frames, 300),
        resize_width=int(args.resize or 0),
        overwrite=bool(args.overwrite),
    )
    print(f"framesWritten: {summary.get('framesWritten')}")
    print(f"durationSec: {summary.get('durationSec')}")
    print(f"runId: {summary.get('runId')}")
    print(f"outPath: {summary.get('outPath')}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
