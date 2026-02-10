from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _tail_ocr_events(events_path: Path, limit: int = 5) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not events_path.exists():
        return rows
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            if str(event.get("name", "")).strip().lower() != "ocr.scan_text":
                continue
            if str(event.get("phase", "")).strip().lower() != "result":
                continue
            payload = event.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            rows.append(
                {
                    "frameSeq": event.get("frameSeq"),
                    "text": payload.get("text"),
                    "latencyMs": event.get("latencyMs"),
                    "model": payload.get("model"),
                }
            )
    return rows[-limit:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run replay with HTTP OCR backend enabled.")
    parser.add_argument("--run-package", required=True)
    parser.add_argument("--ocr-url", default="http://127.0.0.1:19101/ocr")
    parser.add_argument("--risk-url", default="http://127.0.0.1:19101/risk")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8000/ws/events")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--interval-ms", type=int, default=10)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["BYES_OCR_BACKEND"] = "http"
    env["BYES_OCR_HTTP_URL"] = str(args.ocr_url).strip()
    env.setdefault("BYES_OCR_MODEL_ID", "http-ocr")
    env["BYES_RISK_BACKEND"] = "http"
    env["BYES_RISK_HTTP_URL"] = str(args.risk_url).strip()
    env.setdefault("BYES_RISK_MODEL_ID", "http-risk")
    env["BYES_ENABLE_OCR"] = env.get("BYES_ENABLE_OCR", "1")
    env["BYES_ENABLE_RISK"] = env.get("BYES_ENABLE_RISK", "1")
    env["BYES_INFERENCE_EMIT_WS_V1"] = env.get("BYES_INFERENCE_EMIT_WS_V1", "1")

    cmd = [
        sys.executable,
        "scripts/replay_run_package.py",
        "--run-package",
        str(args.run_package),
        "--base-url",
        str(args.base_url),
        "--ws-url",
        str(args.ws_url),
        "--interval-ms",
        str(max(0, int(args.interval_ms))),
    ]
    if str(args.out_dir).strip():
        cmd.extend(["--out-dir", str(args.out_dir).strip()])

    result = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, check=False)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        return int(result.returncode)

    replay_dir: Path | None = None
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        replay_dir_raw = payload.get("replayDir")
        if isinstance(replay_dir_raw, str) and replay_dir_raw.strip():
            replay_dir = Path(replay_dir_raw.strip())
    except Exception:
        pass
    if replay_dir is None or not replay_dir.exists():
        print("[dev_replay_with_http_ocr] replayDir not found in output")
        return 0

    events_path = replay_dir / "events" / "events_v1.jsonl"
    print(f"[dev_replay_with_http_ocr] events={events_path}")
    print("[dev_replay_with_http_ocr] last OCR result rows:")
    for item in _tail_ocr_events(events_path, limit=5):
        print(json.dumps(item, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

