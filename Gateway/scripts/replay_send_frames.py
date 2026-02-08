from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def iter_images(folder: Path) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts])


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay frames to /api/frame")
    parser.add_argument("--dir", required=True, help="folder containing image files")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--interval-ms", type=int, default=500)
    parser.add_argument("--ttl-ms", type=int, default=3000)
    parser.add_argument("--repeat-first", type=int, default=0, help="repeat first image N times")
    parser.add_argument("--preserve-old", action="store_true", help="set preserveOld=true in frame meta")
    args = parser.parse_args()

    folder = Path(args.dir)
    if not folder.exists() or not folder.is_dir():
        print(f"invalid folder: {folder}")
        return 1

    images = iter_images(folder)
    if not images:
        print("no images found")
        return 1
    if args.repeat_first > 0:
        images = [images[0]] * int(args.repeat_first)

    endpoint = args.base_url.rstrip("/") + "/api/frame"
    print(f"sending {len(images)} frames -> {endpoint}")

    with httpx.Client(timeout=10.0) as client:
        for seq, image_path in enumerate(images, start=1):
            ts_capture = int(time.time() * 1000)
            meta = {
                "clientSeq": seq,
                "tsCaptureMs": ts_capture,
                "ttlMs": args.ttl_ms,
                "source": "replay_send_frames",
                "preserveOld": bool(args.preserve_old),
            }
            files = {
                "image": (image_path.name, image_path.read_bytes(), "image/jpeg"),
            }
            data = {"meta": json.dumps(meta, ensure_ascii=False)}
            response = client.post(endpoint, files=files, data=data)
            if response.status_code >= 400:
                print(f"[{seq}] failed status={response.status_code} body={response.text}")
            else:
                print(f"[{seq}] ok {response.json()}")

            if seq < len(images):
                time.sleep(max(0, args.interval_ms) / 1000.0)

    return 0


if __name__ == "__main__":
    sys.exit(main())
