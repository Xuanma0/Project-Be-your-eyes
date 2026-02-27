from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

_STARTED_TS_MS = int(time.time() * 1000)


def read_repo_version() -> str:
    override = str(os.getenv("BYES_VERSION_OVERRIDE", "")).strip()
    if override:
        return override
    try:
        repo_root = Path(__file__).resolve().parents[2]
        version_path = repo_root / "VERSION"
        text = version_path.read_text(encoding="utf-8").strip()
        return text or "unknown"
    except Exception:
        return "unknown"


def get_build_info(*, profile: str | None = None) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    uptime_sec = max(0.0, (now_ms - _STARTED_TS_MS) / 1000.0)
    git_sha = str(os.getenv("BYES_GIT_SHA", "")).strip() or None
    return {
        "version": read_repo_version(),
        "gitSha": git_sha,
        "startedTsMs": int(_STARTED_TS_MS),
        "uptimeSec": round(uptime_sec, 3),
        "profile": str(profile or "").strip().lower() or None,
    }
