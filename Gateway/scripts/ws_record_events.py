from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import websockets


async def run_record(ws_url: str, output: Path, duration_sec: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()

    async with websockets.connect(ws_url, ping_interval=20) as ws:
        with output.open("w", encoding="utf-8") as fp:
            while True:
                if duration_sec > 0 and time.time() - started >= duration_sec:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                received_ms = int(time.time() * 1000)
                payload: dict[str, object]
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"raw": raw}

                line = {
                    "receivedAtMs": received_ms,
                    "event": payload,
                }
                fp.write(json.dumps(line, ensure_ascii=False) + "\n")
                fp.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Record WS events into jsonl")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8000/ws/events")
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-sec", type=int, default=30)
    args = parser.parse_args()

    output = Path(args.output)
    asyncio.run(run_record(args.ws_url, output, args.duration_sec))
    print(f"recorded -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
