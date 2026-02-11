from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _load_manifest(run_package_dir: Path) -> dict[str, Any]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_package_dir / name
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
            break
    raise FileNotFoundError(f"manifest not found in run package: {run_package_dir}")


def _resolve_events_v1_path(run_package_dir: Path, manifest: dict[str, Any]) -> Path:
    rel = str(manifest.get("eventsV1Jsonl", "")).strip()
    if rel:
        candidate = run_package_dir / rel
        if candidate.exists():
            return candidate
    autodetect = run_package_dir / "events" / "events_v1.jsonl"
    if autodetect.exists():
        return autodetect
    ws_rel = str(manifest.get("wsJsonl", "")).strip()
    if ws_rel:
        candidate = run_package_dir / ws_rel
        if candidate.exists():
            return candidate
    raise FileNotFoundError("events_v1 jsonl not found (manifest.eventsV1Jsonl or events/events_v1.jsonl)")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _percentile(values: list[int], p: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(0.0, min(1.0, p / 100.0))
    idx = int(math.ceil(rank * len(ordered)) - 1)
    idx = max(0, min(len(ordered) - 1, idx))
    return int(ordered[idx])


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Bench risk.hazards latency from events_v1")
    parser.add_argument("--run-package", required=True, help="Run package directory")
    args = parser.parse_args()

    run_package_dir = Path(args.run_package)
    if not run_package_dir.exists() or not run_package_dir.is_dir():
        print(f"run package dir not found: {run_package_dir}")
        return 1

    manifest = _load_manifest(run_package_dir)
    events_path = _resolve_events_v1_path(run_package_dir, manifest)

    latencies: list[int] = []
    for row in _iter_jsonl(events_path):
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("category", "")).strip().lower() != "tool":
            continue
        if str(event.get("name", "")).strip().lower() != "risk.hazards":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        latency = _to_int(event.get("latencyMs"))
        if latency is not None and latency >= 0:
            latencies.append(latency)

    payload = {
        "runPackageDir": str(run_package_dir),
        "eventsPath": str(events_path),
        "count": len(latencies),
        "p50": _percentile(latencies, 50),
        "p90": _percentile(latencies, 90),
        "max": max(latencies) if latencies else 0,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
