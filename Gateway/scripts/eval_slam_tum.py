from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.quality_metrics import (  # noqa: E402
    compute_slam_error_metrics,
    extract_pred_slam_from_ws_events,
    load_slam_tum_pose_map,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _find_run_package_dir(root: Path) -> Path:
    if (root / "manifest.json").exists() or (root / "run_manifest.json").exists():
        return root
    manifests = list(root.rglob("manifest.json")) + list(root.rglob("run_manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"manifest not found under {root}")
    manifests.sort(key=lambda path: len(str(path)))
    return manifests[0].parent


def _load_manifest(run_package_dir: Path) -> dict[str, Any]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_package_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            return payload
    return {}


def _resolve_events_path(run_package_dir: Path, manifest: dict[str, Any]) -> Path:
    rel = str(manifest.get("eventsV1Jsonl", "")).strip()
    if rel:
        candidate = run_package_dir / rel
        if candidate.exists():
            return candidate
    for candidate in (
        run_package_dir / "events" / "events_v1.jsonl",
        run_package_dir / "events_v1.jsonl",
        run_package_dir / str(manifest.get("wsJsonl", "")).strip(),
        run_package_dir / "ws_events.jsonl",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"events jsonl not found in run package: {run_package_dir}")


def _guess_traj_label_from_name(path: Path) -> str:
    name = path.name.lower()
    if "online" in name:
        return "online"
    if "final" in name:
        return "final"
    return "auto"


def _select_tum_path(run_package_dir: Path, pred_glob: str, traj_label: str) -> tuple[Path, str]:
    candidates = sorted(run_package_dir.glob(pred_glob))
    if not candidates:
        raise FileNotFoundError(f"no trajectory file matched pred-glob: {pred_glob}")
    label = str(traj_label or "auto").strip().lower() or "auto"
    filtered = candidates
    if label in {"online", "final"}:
        by_label = [path for path in candidates if label in path.name.lower()]
        if by_label:
            filtered = by_label
    if label == "auto":
        online = [path for path in filtered if "online" in path.name.lower()]
        if online:
            selected = online[0]
            return selected, "online"
        final = [path for path in filtered if "final" in path.name.lower()]
        if final:
            selected = final[0]
            return selected, "final"
        selected = filtered[0]
        guessed = _guess_traj_label_from_name(selected)
        return selected, guessed
    selected = filtered[0]
    return selected, label


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    coverage = payload.get("coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    align = payload.get("align")
    align = align if isinstance(align, dict) else {}
    residual = align.get("residualM")
    residual = residual if isinstance(residual, dict) else {}
    lines = [
        "# SLAM Trajectory Eval",
        "",
        f"- runPackage: `{payload.get('runPackage', '')}`",
        f"- predSource: `{payload.get('predSource', '')}`",
        f"- gt: `{payload.get('gtPath', '')}`",
        f"- trajLabel: `{payload.get('trajLabel')}`",
        f"- alignMode: `{payload.get('alignMode')}`",
        "",
        "| ate_rmse_m | ate_mean_m | rpe_trans_rmse_m | coverage_ratio | matchedPairs | totalGt | totalPred | scaleUsed | residualP90(m) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            "| {ate_rmse} | {ate_mean} | {rpe_trans} | {ratio} | {matched} | {total_gt} | {total_pred} | {scale} | {residual_p90} |".format(
                ate_rmse=payload.get("ate_rmse_m"),
                ate_mean=payload.get("ate_mean_m"),
                rpe_trans=payload.get("rpe_trans_rmse_m"),
                ratio=coverage.get("ratio"),
                matched=coverage.get("pairsMatched"),
                total_gt=coverage.get("totalGt"),
                total_pred=coverage.get("totalPred"),
                scale=align.get("scaleUsed"),
                residual_p90=residual.get("p90"),
            )
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def eval_slam_tum(
    *,
    run_package: Path,
    pred_glob: str,
    gt_path: Path | None,
    traj_label: str,
    align_mode: str,
    delta_frames: int,
    out_dir: Path | None,
) -> tuple[dict[str, Any], int]:
    cleanup_dir: Path | None = None
    try:
        run_package_dir = run_package
        if run_package.is_file() and run_package.suffix.lower() == ".zip":
            cleanup_dir = Path(tempfile.mkdtemp(prefix="byes_slam_eval_"))
            with zipfile.ZipFile(run_package, "r") as zf:
                zf.extractall(cleanup_dir)
            run_package_dir = _find_run_package_dir(cleanup_dir)
        run_package_dir = run_package_dir.resolve()
        manifest = _load_manifest(run_package_dir)

        source_mode = str(pred_glob or "events").strip()
        traj_label_used = str(traj_label or "auto").strip().lower() or "auto"
        pred_map: dict[int, dict[str, Any]]
        pred_source = "events"
        selected_pred_path: Path | None = None
        if source_mode.lower() == "events":
            events_path = _resolve_events_path(run_package_dir, manifest)
            pred_map, _event_frames, _lat = extract_pred_slam_from_ws_events(events_path)
        else:
            selected_pred_path, guessed_label = _select_tum_path(run_package_dir, source_mode, traj_label_used)
            pred_map = load_slam_tum_pose_map(selected_pred_path)
            pred_source = str(selected_pred_path)
            if traj_label_used == "auto":
                traj_label_used = guessed_label

        resolved_gt = gt_path if isinstance(gt_path, Path) else None
        if resolved_gt is None:
            candidate = run_package_dir / "gt" / "slam_gt_tum.txt"
            if candidate.exists():
                resolved_gt = candidate
            else:
                alt = run_package_dir / "ground_truth" / "slam_gt_tum.txt"
                if alt.exists():
                    resolved_gt = alt
        if resolved_gt is None or not resolved_gt.exists():
            raise FileNotFoundError("gt trajectory not found (expected gt/slam_gt_tum.txt)")

        gt_map = load_slam_tum_pose_map(resolved_gt)
        metrics = compute_slam_error_metrics(
            gt_map,
            pred_map,
            traj_label=traj_label_used,
            align_mode=align_mode,
            source=str(resolved_gt),
            delta_frames=int(delta_frames),
        )
        coverage = metrics.get("coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        align = metrics.get("align")
        align = align if isinstance(align, dict) else {}

        payload: dict[str, Any] = {
            "schemaVersion": "byes.slam_eval.v1",
            "generatedAtMs": _now_ms(),
            "runPackage": str(run_package_dir),
            "predSource": pred_source,
            "predPath": str(selected_pred_path) if selected_pred_path is not None else None,
            "gtPath": str(resolved_gt),
            "trajLabel": metrics.get("trajLabel"),
            "alignMode": metrics.get("alignMode"),
            "ate_rmse_m": metrics.get("ate_rmse_m"),
            "ate_mean_m": metrics.get("ate_mean_m"),
            "rpe_trans_rmse_m": metrics.get("rpe_trans_rmse_m"),
            "rpe_rot_rmse_deg": metrics.get("rpe_rot_rmse_deg"),
            "coverage": {
                "pairsMatched": int(coverage.get("pairsMatched", 0) or 0),
                "totalGt": int(coverage.get("totalGt", 0) or 0),
                "totalPred": int(coverage.get("totalPred", 0) or 0),
                "ratio": float(coverage.get("ratio", 0.0) or 0.0),
            },
            "align": align,
        }

        output_dir = out_dir.resolve() if isinstance(out_dir, Path) else (run_package_dir / "events" / "slam_eval")
        output_dir.mkdir(parents=True, exist_ok=True)
        latest_json = output_dir / "latest.json"
        latest_md = output_dir / "latest.md"
        latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _write_markdown(latest_md, payload)
        print(json.dumps({"recommendation": {"ate_rmse_m": payload.get("ate_rmse_m"), "rpe_trans_rmse_m": payload.get("rpe_trans_rmse_m")}}, ensure_ascii=False))
        print(f"[out] {latest_json}")
        return payload, 0
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}")
        return {"ok": False, "error": str(exc)}, 1
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate SLAM trajectory against GT TUM")
    parser.add_argument("--run-package", required=True, help="run package dir or zip")
    parser.add_argument(
        "--pred-glob",
        default="events",
        help="trajectory glob relative to run package (e.g. pyslam/*.txt) or 'events'",
    )
    parser.add_argument("--gt", default="", help="path to GT TUM file (default: gt/slam_gt_tum.txt)")
    parser.add_argument("--traj-label", default="auto", choices=["online", "final", "auto"], help="trajectory label")
    parser.add_argument("--align", default="se3", choices=["none", "se3", "sim3"], help="alignment mode")
    parser.add_argument("--delta-frames", type=int, default=1, help="RPE frame delta")
    parser.add_argument("--out", default="", help="output dir (default: <runpkg>/events/slam_eval)")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    payload, exit_code = eval_slam_tum(
        run_package=Path(args.run_package).expanduser().resolve(),
        pred_glob=str(args.pred_glob or "events"),
        gt_path=(Path(args.gt).expanduser().resolve() if str(args.gt or "").strip() else None),
        traj_label=str(args.traj_label or "auto"),
        align_mode=str(args.align or "se3"),
        delta_frames=max(1, int(args.delta_frames or 1)),
        out_dir=(Path(args.out).expanduser().resolve() if str(args.out or "").strip() else None),
    )
    if exit_code != 0:
        return exit_code
    coverage = payload.get("coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    print(
        "[slam_eval] pairsMatched={matched} totalGt={gt} totalPred={pred} ate_rmse_m={ate} rpe_trans_rmse_m={rpe}".format(
            matched=coverage.get("pairsMatched", 0),
            gt=coverage.get("totalGt", 0),
            pred=coverage.get("totalPred", 0),
            ate=payload.get("ate_rmse_m"),
            rpe=payload.get("rpe_trans_rmse_m"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

