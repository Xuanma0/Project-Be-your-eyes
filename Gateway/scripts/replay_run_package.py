from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import websockets

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from report_run import generate_report_outputs, safe_extract_zip  # noqa: E402


@dataclass
class ReplayFrame:
    seq: int
    frame_path: Path
    meta: dict[str, Any]


@dataclass
class ReplayCall:
    method: str
    path: str
    body: dict[str, Any] | None


class WsRecorder:
    def __init__(self, ws_url: str, output_path: Path) -> None:
        self.ws_url = ws_url
        self.output_path = output_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.errors: list[str] = []
        self._write_lock = threading.Lock()

    def start(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run_thread, name="ws-recorder", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.5) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run_thread(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"ws_thread_error:{exc}")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.ws_url, ping_interval=20) as ws:
                    while not self._stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        except Exception as exc:  # noqa: BLE001
                            self.errors.append(f"ws_recv_error:{exc}")
                            break
                        self._write_row(raw)
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"ws_connect_error:{exc}")
                await asyncio.sleep(0.25)

    def _write_row(self, raw: str) -> None:
        received_ms = int(time.time() * 1000)
        event: dict[str, Any]
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                event = parsed
            else:
                event = {"raw": raw}
        except Exception:
            event = {"raw": raw}

        row = {"receivedAtMs": received_ms, "event": event}
        line = json.dumps(row, ensure_ascii=False)
        with self._write_lock:
            with self.output_path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")


def _normalize_base_url(base_url: str) -> str:
    text = (base_url or "").strip()
    if not text:
        return "http://127.0.0.1:8000"
    return text.rstrip("/")


def _normalize_ws_url(ws_url: str) -> str:
    text = (ws_url or "").strip()
    if not text:
        return "ws://127.0.0.1:8000/ws/events"
    return text


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_candidates = [run_dir / "manifest.json", run_dir / "run_manifest.json"]
    for candidate in manifest_candidates:
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
            raise ValueError("manifest payload must be JSON object")
    raise FileNotFoundError(f"manifest.json not found under {run_dir}")


def _resolve_run_package_dir(path: Path) -> tuple[Path, Path | None]:
    if path.is_dir():
        return path, None

    if path.is_file() and path.suffix.lower() == ".zip":
        extract_root = Path(tempfile.mkdtemp(prefix="runpkg_replay_"))
        safe_extract_zip(path, extract_root)

        if (extract_root / "manifest.json").exists() or (extract_root / "run_manifest.json").exists():
            return extract_root, extract_root

        candidates = sorted(
            [p.parent for p in extract_root.rglob("manifest.json")] + [p.parent for p in extract_root.rglob("run_manifest.json")],
            key=lambda p: len(str(p)),
        )
        if not candidates:
            raise FileNotFoundError(f"manifest.json not found in extracted zip: {path}")
        return candidates[0], extract_root

    raise FileNotFoundError(f"run package path not found or unsupported: {path}")


def _load_frames_from_package(run_dir: Path, manifest: dict[str, Any]) -> list[ReplayFrame]:
    frames_meta_rel = str(manifest.get("framesMetaJsonl", "")).strip() or "frames_meta.jsonl"
    frames_dir_rel = str(manifest.get("framesDir", "")).strip() or "frames"
    frames_meta_path = run_dir / frames_meta_rel
    frames_dir = run_dir / frames_dir_rel
    if not frames_meta_path.exists():
        raise FileNotFoundError(f"frames_meta jsonl not found: {frames_meta_path}")

    frames: list[ReplayFrame] = []
    with frames_meta_path.open("r", encoding="utf-8-sig") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            meta_obj = payload.get("meta")
            if not isinstance(meta_obj, dict):
                meta_obj = payload

            seq = int(meta_obj.get("seq", payload.get("seq", 0)) or 0)
            if seq <= 0:
                continue

            frame_rel = str(payload.get("framePath", "")).strip()
            if not frame_rel:
                frame_rel = f"{frames_dir_rel}/frame_{seq}.jpg"
            frame_path = run_dir / frame_rel
            if not frame_path.exists():
                frame_path = frames_dir / f"frame_{seq}.jpg"
            if not frame_path.exists():
                raise FileNotFoundError(f"frame file missing for seq={seq}: {frame_rel}")

            frames.append(ReplayFrame(seq=seq, frame_path=frame_path, meta=meta_obj))

    frames.sort(key=lambda item: item.seq)
    if not frames:
        raise ValueError("no replay frames found in frames_meta.jsonl")
    return frames


def _load_scenario_calls(manifest: dict[str, Any]) -> list[ReplayCall]:
    rows = manifest.get("scenarioApiCalls", [])
    if not isinstance(rows, list):
        return []

    calls: list[ReplayCall] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method", "POST")).strip().upper() or "POST"
        path = str(item.get("path", "/")).strip() or "/"
        body = item.get("body")
        if body is None and isinstance(item.get("payload"), dict):
            body = item.get("payload")
        if body is not None and not isinstance(body, dict):
            body = None
        calls.append(ReplayCall(method=method, path=path, body=body))
    return calls


def _build_replay_dir(out_dir: Path | None, source_name: str, scenario_tag: str) -> Path:
    root = out_dir if out_dir is not None else Path.cwd() / "_replays"
    root.mkdir(parents=True, exist_ok=True)
    safe_tag = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in scenario_tag.strip() or "scenario")
    run_name = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{safe_tag}_{source_name}"
    replay_dir = root / run_name
    replay_dir.mkdir(parents=True, exist_ok=False)
    return replay_dir


def _write_metrics_snapshot(client: httpx.Client, url: str, output: Path) -> None:
    response = client.get(url, timeout=10.0)
    response.raise_for_status()
    output.write_text(response.text, encoding="utf-8")


def _execute_call(client: httpx.Client, base_url: str, call: ReplayCall, call_log: list[dict[str, Any]]) -> None:
    url = f"{base_url}{call.path if call.path.startswith('/') else '/' + call.path}"
    started = _now_ms()
    if call.method == "GET":
        response = client.get(url, timeout=10.0)
    else:
        response = client.request(call.method, url, json=call.body or {}, timeout=10.0)
    latency = max(0, _now_ms() - started)
    call_log.append(
        {
            "atMs": _now_ms(),
            "method": call.method,
            "path": call.path,
            "body": call.body,
            "statusCode": response.status_code,
            "latencyMs": latency,
        }
    )
    response.raise_for_status()


def _post_frames(
    client: httpx.Client,
    base_url: str,
    frames: list[ReplayFrame],
    interval_ms: int,
    call_log: list[dict[str, Any]],
) -> int:
    sent = 0
    for frame in frames:
        url = f"{base_url}/api/frame"
        payload_meta = json.dumps(frame.meta, ensure_ascii=False, separators=(",", ":"))
        content = frame.frame_path.read_bytes()
        started = _now_ms()
        response = client.post(
            url,
            data={"meta": payload_meta},
            files={"image": (frame.frame_path.name, content, "image/jpeg")},
            timeout=20.0,
        )
        latency = max(0, _now_ms() - started)
        call_log.append(
            {
                "atMs": _now_ms(),
                "method": "POST",
                "path": "/api/frame",
                "body": {"seq": frame.seq, "meta": frame.meta},
                "statusCode": response.status_code,
                "latencyMs": latency,
            }
        )
        response.raise_for_status()
        sent += 1
        if interval_ms > 0:
            time.sleep(interval_ms / 1000.0)
    return sent


def _copy_replay_inputs(replay_dir: Path, frames: list[ReplayFrame], scenario_calls: list[ReplayCall]) -> tuple[Path, Path, int]:
    frames_dir = replay_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames_meta_path = replay_dir / "frames_meta.jsonl"
    frames_index_path = replay_dir / "frames_index.jsonl"

    with frames_meta_path.open("w", encoding="utf-8") as meta_fp, frames_index_path.open("w", encoding="utf-8") as index_fp:
        for frame in frames:
            target_name = f"frame_{frame.seq}.jpg"
            target_path = frames_dir / target_name
            shutil.copy2(frame.frame_path, target_path)
            data = target_path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            meta_row = {
                "seq": frame.seq,
                "framePath": f"frames/{target_name}",
                "meta": frame.meta,
                "bytes": len(data),
            }
            index_row = {
                "seq": frame.seq,
                "path": f"frames/{target_name}",
                "bytes": len(data),
                "sha256": sha,
            }
            meta_fp.write(json.dumps(meta_row, ensure_ascii=False) + "\n")
            index_fp.write(json.dumps(index_row, ensure_ascii=False) + "\n")

    # keep scenario_calls referenced for parity with Unity output schema.
    _ = scenario_calls
    return frames_meta_path, frames_index_path, len(frames)


def replay_run_package(
    *,
    run_package: Path,
    base_url: str,
    ws_url: str,
    out_dir: Path | None,
    interval_ms: int,
    apply_scenario_calls: bool = True,
    do_reset: bool = True,
    record_ws: bool = True,
    auto_upload: bool = False,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    normalized_base_url = _normalize_base_url(base_url)
    normalized_ws_url = _normalize_ws_url(ws_url)
    source_dir, cleanup_dir = _resolve_run_package_dir(run_package)
    manifest = _load_manifest(source_dir)
    frames = _load_frames_from_package(source_dir, manifest)
    scenario_calls = _load_scenario_calls(manifest)

    source_name = run_package.stem if run_package.suffix.lower() == ".zip" else source_dir.name
    scenario_tag = str(manifest.get("scenarioTag", "") or "replay")
    replay_dir = _build_replay_dir(out_dir, source_name, scenario_tag)
    metrics_before = replay_dir / "metrics_before.txt"
    metrics_after = replay_dir / "metrics_after.txt"
    ws_jsonl = replay_dir / "ws_events.jsonl"
    report_md = replay_dir / "report.md"
    report_json = replay_dir / "report.json"

    _, _, copied_frames_count = _copy_replay_inputs(replay_dir, frames, scenario_calls)

    if not ws_jsonl.exists():
        ws_jsonl.write_text("", encoding="utf-8")

    errors: list[str] = []
    call_log: list[dict[str, Any]] = []
    ws_recorder: WsRecorder | None = None
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=20.0)

    start_ms = _now_ms()
    sent_frames = 0
    upload_result: dict[str, Any] | None = None

    try:
        if do_reset:
            _execute_call(client, normalized_base_url, ReplayCall(method="POST", path="/api/dev/reset", body={}), call_log)

        if apply_scenario_calls:
            for call in scenario_calls:
                try:
                    _execute_call(client, normalized_base_url, call, call_log)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"scenario_call_failed:{call.method}:{call.path}:{exc}")

        try:
            _write_metrics_snapshot(client, f"{normalized_base_url}/metrics", metrics_before)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"metrics_before_failed:{exc}")
            metrics_before.write_text("", encoding="utf-8")

        if record_ws:
            ws_recorder = WsRecorder(normalized_ws_url, ws_jsonl)
            ws_recorder.start()

        sent_frames = _post_frames(client, normalized_base_url, frames, interval_ms, call_log)
        time.sleep(0.35)

        if ws_recorder is not None:
            ws_recorder.stop()
            if ws_recorder.errors:
                errors.extend(ws_recorder.errors)

        try:
            _write_metrics_snapshot(client, f"{normalized_base_url}/metrics", metrics_after)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"metrics_after_failed:{exc}")
            metrics_after.write_text("", encoding="utf-8")

        run_summary = {
            "runPackageDir": str(replay_dir),
            "scenarioTag": scenario_tag,
            "startMs": start_ms,
            "endMs": _now_ms(),
            "frameCountSent": sent_frames,
            "eventCountAccepted": sum(1 for _ in ws_jsonl.open("r", encoding="utf-8")),
            "localSafetyFallbackEnterCount": 0,
            "healthStatusCounts": {},
            "errors": errors,
        }
        generate_report_outputs(
            ws_jsonl=ws_jsonl,
            output=report_md,
            metrics_url=f"{normalized_base_url}/metrics",
            metrics_before_path=metrics_before,
            metrics_after_path=metrics_after,
            external_readiness_url=f"{normalized_base_url}/api/external_readiness",
            run_package_summary=run_summary,
            output_json=report_json,
        )

        if auto_upload:
            replay_zip = replay_dir.parent / f"{replay_dir.name}.zip"
            if replay_zip.exists():
                replay_zip.unlink()
            with zipfile.ZipFile(replay_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for item in replay_dir.rglob("*"):
                    if item.is_file():
                        zf.write(item, item.relative_to(replay_dir))
            try:
                resp = client.post(
                    f"{normalized_base_url}/api/run_package/upload",
                    data={"scenarioTag": scenario_tag},
                    files={"file": (replay_zip.name, replay_zip.read_bytes(), "application/zip")},
                    timeout=30.0,
                )
                resp.raise_for_status()
                upload_payload = resp.json()
                if isinstance(upload_payload, dict):
                    upload_result = upload_payload
            except Exception as exc:  # noqa: BLE001
                errors.append(f"auto_upload_failed:{exc}")

        end_ms = _now_ms()
        replay_manifest = {
            "scenarioTag": scenario_tag,
            "startMs": start_ms,
            "endMs": end_ms,
            "baseUrl": normalized_base_url,
            "wsUrl": normalized_ws_url,
            "sessionId": str(manifest.get("sessionId", "default")),
            "sourceRunPackage": str(run_package),
            "wsJsonl": "ws_events.jsonl",
            "metricsBefore": "metrics_before.txt",
            "metricsAfter": "metrics_after.txt",
            "framesDir": "frames",
            "framesMetaJsonl": "frames_meta.jsonl",
            "framesIndexJsonl": "frames_index.jsonl",
            "framesCount": copied_frames_count,
            "frameCountSent": sent_frames,
            "eventCountAccepted": sum(1 for _ in ws_jsonl.open("r", encoding="utf-8")),
            "localSafetyFallbackEnterCount": 0,
            "healthStatusCounts": {},
            "scenarioApiCalls": [
                {"method": c.method, "path": c.path, "body": c.body} for c in scenario_calls
            ],
            "appliedScenarioCalls": call_log,
            "errors": errors,
        }
        if upload_result is not None:
            replay_manifest["upload"] = upload_result
        (replay_dir / "manifest.json").write_text(
            json.dumps(replay_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "replayDir": str(replay_dir),
            "reportMdPath": str(report_md),
            "reportJsonPath": str(report_json),
            "sentFrames": sent_frames,
            "wsRows": replay_manifest["eventCountAccepted"],
            "errors": errors,
        }
    finally:
        if ws_recorder is not None:
            ws_recorder.stop()
        if owns_client and client is not None:
            client.close()
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a run package by re-posting captured frames to Gateway.")
    parser.add_argument("--run-package", required=True, help="Run package directory or zip path")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8000/ws/events")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--interval-ms", type=int, default=10)
    parser.add_argument("--apply-scenario-calls", dest="apply_scenario_calls", action="store_true", default=True)
    parser.add_argument("--skip-scenario-calls", dest="apply_scenario_calls", action="store_false")
    parser.add_argument("--reset", dest="do_reset", action="store_true", default=True)
    parser.add_argument("--no-reset", dest="do_reset", action="store_false")
    parser.add_argument("--no-ws", dest="record_ws", action="store_false", default=True)
    parser.add_argument("--auto-upload", action="store_true", default=False)
    args = parser.parse_args()

    run_package = Path(args.run_package)
    out_dir = Path(args.out_dir) if args.out_dir else None
    try:
        result = replay_run_package(
            run_package=run_package,
            base_url=args.base_url,
            ws_url=args.ws_url,
            out_dir=out_dir,
            interval_ms=max(0, int(args.interval_ms)),
            apply_scenario_calls=bool(args.apply_scenario_calls),
            do_reset=bool(args.do_reset),
            record_ws=bool(args.record_ws),
            auto_upload=bool(args.auto_upload),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"replay failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
