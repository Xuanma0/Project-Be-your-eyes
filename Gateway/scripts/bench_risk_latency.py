from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.latency_stats import extract_risk_hazard_latencies, iter_jsonl, summarize_latency

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Bench risk.hazards latency from events_v1")
    parser.add_argument("--run-package", required=True, help="Run package directory")
    parser.add_argument("--json-out", default="", help="Optional output path for JSON payload")
    args = parser.parse_args()

    run_package_dir = Path(args.run_package)
    if not run_package_dir.exists() or not run_package_dir.is_dir():
        print(f"run package dir not found: {run_package_dir}")
        return 1

    manifest = _load_manifest(run_package_dir)
    events_path = _resolve_events_v1_path(run_package_dir, manifest)

    latencies = extract_risk_hazard_latencies(iter_jsonl(events_path))
    stats = summarize_latency(latencies)

    payload = {
        "runPackageDir": str(run_package_dir),
        "eventsPath": str(events_path),
        **stats,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    json_out = str(args.json_out or "").strip()
    if json_out:
        out_path = Path(json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
