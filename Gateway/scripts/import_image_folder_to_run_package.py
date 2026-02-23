from __future__ import annotations

import argparse
import json
import random
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


def _to_nonnegative_int(raw: Any, default: int) -> int:
    try:
        value = int(raw)
        if value < 0:
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


def import_image_folder(
    *,
    image_dir: Path,
    out_dir: Path,
    glob_pattern: str,
    sample: int,
    shuffle: bool,
    seed: int,
    run_id: str | None,
    overwrite: bool,
) -> tuple[dict[str, Any], int]:
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("OpenCV (cv2) is required for image-folder import") from exc

    if not image_dir.exists() or not image_dir.is_dir():
        raise FileNotFoundError(f"image directory not found: {image_dir}")

    _prepare_output_dir(out_dir, overwrite=overwrite)
    run_id_safe = _safe_run_id(run_id, fallback_prefix="imagenet_import")

    files = [path for path in image_dir.rglob(glob_pattern) if path.is_file()]
    files.sort(key=lambda p: p.as_posix().lower())
    found_count = len(files)

    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(files)
    if sample > 0:
        files = files[:sample]

    used_rows: list[dict[str, Any]] = []
    warnings_count = 0
    for idx, src in enumerate(files, start=1):
        image = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if image is None:
            warnings_count += 1
            continue
        frame_name = f"frame_{idx:06d}.jpg"
        frame_rel = f"frames/{frame_name}"
        frame_path = out_dir / frame_rel
        ok = cv2.imwrite(str(frame_path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not ok:
            warnings_count += 1
            continue

        capture_ts_ms = int((idx - 1) * 200)
        h, w = image.shape[:2]
        source_meta = {
            "type": "imagenet",
            "imageDir": str(image_dir),
            "glob": glob_pattern,
            "sourcePath": str(src),
        }
        row = {
            "frameSeq": int(idx),
            "seq": int(idx),
            "framePath": frame_rel,
            "captureTsMs": capture_ts_ms,
            "tsMs": capture_ts_ms,
            "source": source_meta,
            "meta": {
                "seq": int(idx),
                "timestampMs": capture_ts_ms,
                "captureTsMs": capture_ts_ms,
                "width": int(w),
                "height": int(h),
                "source": source_meta,
            },
        }
        used_rows.append(row)

    frames_meta_path = out_dir / "frames_meta.jsonl"
    with frames_meta_path.open("w", encoding="utf-8") as fp:
        for row in used_rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    events_path = out_dir / "events" / "events_v1.jsonl"
    events_path.write_text("", encoding="utf-8")

    metrics_before_path = out_dir / "metrics_before.txt"
    metrics_after_path = out_dir / "metrics_after.txt"
    _write_min_metrics(metrics_before_path, len(used_rows))
    _write_min_metrics(metrics_after_path, len(used_rows))

    manifest = {
        "runId": run_id_safe,
        "scenarioTag": "import_image_folder",
        "datasetTag": "imagenet_det_test",
        "source": {
            "type": "imagenet",
            "imageDir": str(image_dir),
            "glob": glob_pattern,
            "shuffle": bool(shuffle),
            "seed": int(seed),
        },
        "framesDir": "frames",
        "framesMetaJsonl": "frames_meta.jsonl",
        "eventsV1Jsonl": "events/events_v1.jsonl",
        "wsJsonl": "events/events_v1.jsonl",
        "metricsBefore": "metrics_before.txt",
        "metricsAfter": "metrics_after.txt",
        "framesCount": int(len(used_rows)),
        "frameCountSent": int(len(used_rows)),
        "eventCountAccepted": 0,
        "errors": [],
        "importSummary": {
            "imagesFound": int(found_count),
            "imagesUsed": int(len(used_rows)),
            "warningsCount": int(warnings_count),
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "imagesFound": int(found_count),
        "used": int(len(used_rows)),
        "outPath": str(out_dir),
        "runId": run_id_safe,
        "warningsCount": int(warnings_count),
    }
    return summary, 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import image folder into BYE run-package format")
    parser.add_argument("--image-dir", required=True, help="Source image directory")
    parser.add_argument("--out", required=True, help="Output run-package directory")
    parser.add_argument("--glob", default="*.JPEG", help="Glob pattern for source images")
    parser.add_argument("--sample", type=int, default=200, help="Max number of images to include (<=0 means all)")
    parser.add_argument("--shuffle", type=int, default=1, help="Whether to shuffle selected files (1 or 0)")
    parser.add_argument("--seed", type=int, default=123, help="Random seed for shuffle")
    parser.add_argument("--run-id", default="", help="Optional runId override")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    summary, exit_code = import_image_folder(
        image_dir=Path(args.image_dir).resolve(),
        out_dir=Path(args.out).resolve(),
        glob_pattern=str(args.glob or "*.JPEG").strip() or "*.JPEG",
        sample=_to_nonnegative_int(args.sample, 200),
        shuffle=bool(int(args.shuffle)),
        seed=int(args.seed),
        run_id=str(args.run_id or "").strip() or None,
        overwrite=bool(args.overwrite),
    )
    print(f"imagesFound: {summary.get('imagesFound')}")
    print(f"used: {summary.get('used')}")
    print(f"warningsCount: {summary.get('warningsCount')}")
    print(f"runId: {summary.get('runId')}")
    print(f"outPath: {summary.get('outPath')}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
