from __future__ import annotations

import os
import shutil
import tempfile
import pytest
from pathlib import Path

_SERIAL_SERVICE_KEYWORDS = (
    "e2e",
    "http_reference",
    "reference_",
    "sam3",
    "da3",
    "planner_service",
    "inference_service",
    "uvicorn",
    "benchmark",
    "run_packages",
    "run_package",
    "upload",
    "runs",
    "runs_",
    "leaderboard",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    cached_file_flags: dict[Path, bool] = {}

    def _needs_serial_from_file(path: Path) -> bool:
        cached = cached_file_flags.get(path)
        if cached is not None:
            return cached
        try:
            content = path.read_text(encoding="utf-8-sig")
        except Exception:
            cached_file_flags[path] = False
            return False
        lowered = content.lower()
        flagged = (
            "from main import app" in lowered
            or "testclient(app)" in lowered
            or "/api/run_package/upload" in lowered
        )
        cached_file_flags[path] = flagged
        return flagged

    for item in items:
        nodeid = str(item.nodeid).lower()
        if any(keyword in nodeid for keyword in _SERIAL_SERVICE_KEYWORDS):
            item.add_marker(pytest.mark.xdist_group("serial_services"))
            continue
        item_path = Path(str(getattr(item, "fspath", "")))
        if item_path.is_file() and _needs_serial_from_file(item_path):
            item.add_marker(pytest.mark.xdist_group("serial_services"))


@pytest.fixture(scope="session", autouse=True)
def _isolate_run_packages_root_per_worker() -> None:
    worker_id = str(os.getenv("PYTEST_XDIST_WORKER", "")).strip()
    if not worker_id:
        return
    try:
        import main as gateway_main  # noqa: PLC0415
    except Exception:
        return

    isolated_root = Path(tempfile.gettempdir()) / f"byes_gateway_run_packages_{worker_id}"
    shutil.rmtree(isolated_root, ignore_errors=True)
    isolated_root.mkdir(parents=True, exist_ok=True)
    gateway_main.gateway.run_packages_root = isolated_root
    gateway_main.gateway.run_packages_index_path = isolated_root / "index.json"
