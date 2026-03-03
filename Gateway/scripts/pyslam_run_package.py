from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _parse_tum_to_json(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            ts = float(parts[0])
            tx, ty, tz = float(parts[1]), float(parts[2]), float(parts[3])
            qx, qy, qz, qw = float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])
        except Exception:
            continue
        rows.append(
            {
                "ts": ts,
                "t": [tx, ty, tz],
                "q": [qx, qy, qz, qw],
                "status": "tracking",
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run optional pySLAM pipeline for a run package and export trajectory.json")
    parser.add_argument("--run-package", required=True)
    parser.add_argument("--pyslam-root", default="", help="fallback to BYES_PYSLAM_REPO_PATH env")
    parser.add_argument("--mode", default="fixture", choices=["fixture", "wsl"])
    parser.add_argument("--config", default="")
    args = parser.parse_args()

    run_package = Path(args.run_package).expanduser().resolve()
    if not run_package.exists():
        print(f"run package not found: {run_package}")
        return 1

    pyslam_root = str(args.pyslam_root or "").strip()
    if not pyslam_root:
        pyslam_root = str(__import__("os").environ.get("BYES_PYSLAM_REPO_PATH", "")).strip()
    if not pyslam_root:
        print("missing pySLAM root; set --pyslam-root or BYES_PYSLAM_REPO_PATH")
        return 2

    gateway_dir = Path(__file__).resolve().parents[1]
    runner = gateway_dir / "scripts" / "run_pyslam_on_run_package.py"
    out_dir = run_package / "out" / "pyslam"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(runner),
        "--run-package",
        str(run_package),
        "--mode",
        str(args.mode),
        "--out-dir",
        str(out_dir),
        "--pyslam-root",
        str(pyslam_root),
    ]
    if str(args.config or "").strip():
        cmd.extend(["--config", str(args.config).strip()])

    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        return int(result.returncode)

    trajectory_candidates = sorted(out_dir.glob("*.txt"))
    if not trajectory_candidates:
        print(f"no trajectory txt found under {out_dir}")
        return 2

    best = trajectory_candidates[0]
    rows = _parse_tum_to_json(best)
    trajectory_json = out_dir / "trajectory.json"
    trajectory_json.write_text(json.dumps({"schemaVersion": "byes.pyslam.trajectory.v1", "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[pyslam_run_package] trajectory json: {trajectory_json}")
    print(f"[pyslam_run_package] source tum: {best}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
