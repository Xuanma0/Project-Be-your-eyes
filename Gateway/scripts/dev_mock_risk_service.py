from __future__ import annotations

import argparse
import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class RiskHandler(BaseHTTPRequestHandler):
    server_version = "byes-dev-risk/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        del format, args

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/risk":
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return

        delay_ms = max(0, int(os.getenv("BYES_DEV_RISK_DELAY_MS", "0") or "0"))
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {}

        frame_seq = payload.get("frameSeq")
        hazards: list[dict[str, Any]]
        if isinstance(frame_seq, int) and frame_seq % 3 == 0:
            hazards = [{"hazardKind": "dropoff", "severity": "critical"}]
        else:
            hazards = [{"hazardKind": "stair_down", "severity": "warning"}]

        body = {
            "hazards": hazards,
            "latencyMs": delay_ms,
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal dev risk HTTP backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9002)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), RiskHandler)
    print(f"[dev-mock-risk] serving http://{args.host}:{args.port}/risk")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
