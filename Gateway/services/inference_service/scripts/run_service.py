from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run BYES reference inference service via uvicorn.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19101)
    args = parser.parse_args(argv)

    service_dir = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    provider = str(env.get("BYES_SERVICE_OCR_PROVIDER", "reference")).strip().lower() or "reference"
    model = str(env.get("BYES_SERVICE_OCR_MODEL_ID", "")).strip() or "(provider default)"
    print(f"[run_service] provider={provider} model={model} host={args.host} port={args.port}")
    print("[run_service] endpoint /ocr and /risk")

    cmd = [sys.executable, "-m", "uvicorn", "app:app", "--host", str(args.host), "--port", str(args.port)]
    return subprocess.call(cmd, cwd=service_dir, env=env)


if __name__ == "__main__":
    raise SystemExit(main())

