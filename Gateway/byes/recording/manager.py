from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sanitize_token(raw: str) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return "default"
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "default"


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False))
        fp.write("\n")


@dataclass
class _RecordingSession:
    device_id: str
    run_id: str
    note: str
    start_ms: int
    max_sec: int
    max_frames: int
    root_dir: Path
    frames_dir: Path
    frames_meta_path: Path
    events_v1_path: Path
    ws_events_path: Path
    metrics_before_path: Path
    metrics_after_path: Path
    assets_dir: Path
    frame_count: int = 0
    event_count: int = 0
    asset_count: int = 0
    run_frame_index: dict[tuple[str, int], bool] = field(default_factory=dict)
    copied_assets: set[str] = field(default_factory=set)
    closed: bool = False

    def is_expired(self) -> bool:
        if self.max_sec <= 0:
            return False
        return (_now_ms() - int(self.start_ms)) >= (self.max_sec * 1000)


class RecordingManager:
    def __init__(
        self,
        *,
        run_packages_root: Path,
        asset_resolver: Callable[[str], tuple[bytes, str] | None] | None = None,
    ) -> None:
        self._root = Path(run_packages_root).resolve() / "quest_recordings"
        self._lock = threading.Lock()
        self._sessions: dict[str, _RecordingSession] = {}
        self._asset_resolver = asset_resolver

    def set_asset_resolver(self, resolver: Callable[[str], tuple[bytes, str] | None] | None) -> None:
        self._asset_resolver = resolver

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()

    def start(
        self,
        *,
        device_id: str,
        note: str = "",
        max_sec: int = 120,
        max_frames: int = 0,
    ) -> dict[str, Any]:
        normalized_device = str(device_id or "default").strip() or "default"
        with self._lock:
            existing = self._sessions.get(normalized_device)
            if existing is not None and not existing.closed:
                raise ValueError(f"recording already active for deviceId={normalized_device}")

            start_ms = _now_ms()
            run_id = f"quest_recording_{_sanitize_token(normalized_device)}_{start_ms}"
            root_dir = self._root / run_id
            frames_dir = root_dir / "frames"
            events_dir = root_dir / "events"
            frames_meta_path = root_dir / "frames_meta.jsonl"
            events_v1_path = events_dir / "events_v1.jsonl"
            ws_events_path = root_dir / "ws_events.jsonl"
            metrics_before_path = root_dir / "metrics_before.txt"
            metrics_after_path = root_dir / "metrics_after.txt"
            assets_dir = root_dir / "assets"

            frames_dir.mkdir(parents=True, exist_ok=True)
            events_dir.mkdir(parents=True, exist_ok=True)
            assets_dir.mkdir(parents=True, exist_ok=True)
            metrics_before_path.write_text("# recording started\n", encoding="utf-8")
            metrics_after_path.write_text("# recording stopped\n", encoding="utf-8")

            session = _RecordingSession(
                device_id=normalized_device,
                run_id=run_id,
                note=str(note or "").strip(),
                start_ms=start_ms,
                max_sec=max(0, int(max_sec)),
                max_frames=max(0, int(max_frames)),
                root_dir=root_dir,
                frames_dir=frames_dir,
                frames_meta_path=frames_meta_path,
                events_v1_path=events_v1_path,
                ws_events_path=ws_events_path,
                metrics_before_path=metrics_before_path,
                metrics_after_path=metrics_after_path,
                assets_dir=assets_dir,
            )
            self._sessions[normalized_device] = session

            return {
                "ok": True,
                "deviceId": normalized_device,
                "runId": run_id,
                "recordingPath": str(root_dir),
                "startedTsMs": start_ms,
                "maxSec": session.max_sec,
                "maxFrames": session.max_frames,
            }

    def stop(self, *, device_id: str, base_url: str, ws_url: str) -> dict[str, Any]:
        normalized_device = str(device_id or "default").strip() or "default"
        with self._lock:
            session = self._sessions.get(normalized_device)
            if session is None or session.closed:
                raise ValueError(f"no active recording for deviceId={normalized_device}")

            session.closed = True
            end_ms = _now_ms()
            manifest = {
                "scenarioTag": "quest_recording",
                "startMs": int(session.start_ms),
                "endMs": int(end_ms),
                "baseUrl": str(base_url or "").strip() or None,
                "wsUrl": str(ws_url or "").strip() or None,
                "sessionId": session.run_id,
                "wsJsonl": "ws_events.jsonl",
                "eventsV1Jsonl": "events/events_v1.jsonl",
                "metricsBefore": "metrics_before.txt",
                "metricsAfter": "metrics_after.txt",
                "assetsDir": "assets",
                "framesDir": "frames",
                "framesMetaJsonl": "frames_meta.jsonl",
                "framesCount": int(session.frame_count),
                "frameCountSent": int(session.frame_count),
                "eventCountAccepted": int(session.event_count),
                "assetCount": int(session.asset_count),
                "errors": [],
                "recording": {
                    "deviceId": session.device_id,
                    "note": session.note or None,
                },
            }
            (session.root_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            return {
                "ok": True,
                "deviceId": normalized_device,
                "runId": session.run_id,
                "recordingPath": str(session.root_dir),
                "manifestPath": str(session.root_dir / "manifest.json"),
                "framesCount": int(session.frame_count),
                "eventCount": int(session.event_count),
                "endedTsMs": end_ms,
            }

    def on_frame(
        self,
        *,
        device_id: str,
        run_id: str,
        frame_seq: int,
        frame_bytes: bytes,
        meta: dict[str, Any],
        recv_ts_ms: int,
    ) -> None:
        normalized_device = str(device_id or "default").strip() or "default"
        with self._lock:
            session = self._sessions.get(normalized_device)
            if session is None or session.closed or session.is_expired():
                return
            if session.max_frames > 0 and session.frame_count >= session.max_frames:
                return

            safe_seq = max(1, int(frame_seq))
            frame_name = f"frame_{safe_seq}.jpg"
            frame_path = session.frames_dir / frame_name
            frame_path.write_bytes(bytes(frame_bytes or b""))
            capture_ts_ms = _to_nonnegative_int_or_none((meta or {}).get("captureTsMs"))
            row = {
                "frameSeq": safe_seq,
                "path": f"frames/{frame_name}",
                "captureTsMs": capture_ts_ms,
                "tsMs": int(max(0, recv_ts_ms)),
                "meta": dict(meta or {}),
            }
            _append_jsonl(session.frames_meta_path, row)
            session.frame_count += 1
            session.run_frame_index[(str(run_id or "").strip() or "unknown-run", safe_seq)] = True

    def on_event(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        run_id = str(event.get("runId", "") or "").strip()
        frame_seq = _to_nonnegative_int_or_none(event.get("frameSeq"))
        with self._lock:
            if not self._sessions:
                return

            matched: _RecordingSession | None = None
            if run_id and frame_seq is not None:
                key = (run_id, int(frame_seq))
                for session in self._sessions.values():
                    if session.closed or session.is_expired():
                        continue
                    if key in session.run_frame_index:
                        matched = session
                        break

            if matched is None:
                live_sessions = [s for s in self._sessions.values() if not s.closed and not s.is_expired()]
                if len(live_sessions) == 1:
                    matched = live_sessions[0]
                else:
                    return

            _append_jsonl(matched.events_v1_path, event)
            _append_jsonl(matched.ws_events_path, event)
            matched.event_count += 1
            self._copy_assets_for_event_unlocked(matched, event)

    def _copy_assets_for_event_unlocked(self, session: _RecordingSession, event: dict[str, Any]) -> None:
        resolver = self._asset_resolver
        if resolver is None:
            return
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return
        asset_ids = _collect_asset_ids(payload)
        for asset_id in asset_ids:
            if asset_id in session.copied_assets:
                continue
            resolved = resolver(asset_id)
            if resolved is None:
                continue
            data, content_type = resolved
            ext = _asset_ext_from_content_type(content_type)
            file_name = f"{asset_id}{ext}"
            out_path = session.assets_dir / file_name
            out_path.write_bytes(bytes(data or b""))
            session.asset_count += 1
            session.copied_assets.add(asset_id)


def _to_nonnegative_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    if parsed < 0:
        return None
    return parsed


def _collect_asset_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    direct = str(payload.get("assetId", "")).strip()
    if direct:
        ids.append(direct)
    raw_list = payload.get("assetIds")
    if isinstance(raw_list, list):
        for item in raw_list:
            text = str(item or "").strip()
            if text:
                ids.append(text)
    return sorted(set(ids))


def _asset_ext_from_content_type(content_type: str) -> str:
    normalized = str(content_type or "").strip().lower()
    if "png" in normalized:
        return ".png"
    if "webp" in normalized:
        return ".webp"
    if "jpeg" in normalized or "jpg" in normalized:
        return ".jpg"
    if "json" in normalized:
        return ".json"
    return ".bin"
