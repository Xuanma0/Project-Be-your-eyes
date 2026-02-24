from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any


THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
REPO_ROOT = GATEWAY_ROOT.parent
DEFAULT_CONTRACTS_DIR = GATEWAY_ROOT / "contracts"
DEFAULT_LOCK_PATH = DEFAULT_CONTRACTS_DIR / "contract.lock.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _schema_version_from_filename(path: Path) -> str:
    name = path.name
    if name.lower().endswith(".json"):
        return name[:-5]
    return name


def _scan_contracts(contracts_dir: Path) -> dict[str, dict[str, Any]]:
    if not contracts_dir.exists() or not contracts_dir.is_dir():
        raise FileNotFoundError(f"contracts dir not found: {contracts_dir}")
    versions: dict[str, dict[str, Any]] = {}
    for path in sorted(contracts_dir.glob("*.json")):
        if path.name == "contract.lock.json":
            continue
        version = _schema_version_from_filename(path)
        versions[version] = {
            "version": version,
            "path": str(path.relative_to(REPO_ROOT).as_posix()),
            "sha256": _sha256_file(path),
            "updatedAtMs": int(path.stat().st_mtime * 1000),
        }
    return versions


def _render_lock_payload(versions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": "byes.contract.lock.v1",
        "generatedAtMs": _now_ms(),
        "versions": versions,
    }


def _read_lock(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"contract lock must be object: {path}")
    versions = payload.get("versions")
    if not isinstance(versions, dict):
        raise ValueError(f"contract lock missing versions object: {path}")
    return payload


def _compare_lock(current: dict[str, dict[str, Any]], lock: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    locked_versions = lock.get("versions")
    locked_versions = locked_versions if isinstance(locked_versions, dict) else {}

    current_keys = set(current.keys())
    lock_keys = set(str(key) for key in locked_versions.keys())
    missing = sorted(lock_keys - current_keys)
    extra = sorted(current_keys - lock_keys)
    if missing:
        errors.append(f"missing contract files for versions: {', '.join(missing)}")
    if extra:
        errors.append(f"new contract files not in lock: {', '.join(extra)}")

    shared = sorted(current_keys & lock_keys)
    for version in shared:
        cur = current.get(version, {})
        locked_raw = locked_versions.get(version)
        locked = locked_raw if isinstance(locked_raw, dict) else {}
        cur_sha = str(cur.get("sha256", ""))
        lock_sha = str(locked.get("sha256", ""))
        if cur_sha != lock_sha:
            errors.append(
                f"{version}: sha256 mismatch current={cur_sha or '<empty>'} lock={lock_sha or '<empty>'}"
            )
        cur_path = str(cur.get("path", ""))
        lock_path = str(locked.get("path", ""))
        if cur_path != lock_path:
            errors.append(
                f"{version}: path mismatch current={cur_path or '<empty>'} lock={lock_path or '<empty>'}"
            )
    return errors


def _print_summary(versions: dict[str, dict[str, Any]]) -> None:
    print("[contracts]")
    for version in sorted(versions.keys()):
        row = versions.get(version, {})
        print(
            f"- {version}: sha256={row.get('sha256', '')} path={row.get('path', '')} updatedAtMs={row.get('updatedAtMs', 0)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze and verify Gateway contract schema hashes.")
    parser.add_argument(
        "--contracts-dir",
        default=str(DEFAULT_CONTRACTS_DIR),
        help="Contracts directory (default: Gateway/contracts)",
    )
    parser.add_argument(
        "--lock-path",
        default=str(DEFAULT_LOCK_PATH),
        help="Path to contract.lock.json (default: Gateway/contracts/contract.lock.json)",
    )
    parser.add_argument("--write-lock", action="store_true", default=False, help="Write/update contract lock file")
    parser.add_argument("--check-lock", action="store_true", default=False, help="Check current contracts against lock")
    args = parser.parse_args(argv)

    contracts_dir = Path(args.contracts_dir).resolve()
    lock_path = Path(args.lock_path).resolve()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    versions = _scan_contracts(contracts_dir)
    if not versions:
        print(f"no contracts found in: {contracts_dir}")
        return 1

    if args.write_lock:
        payload = _render_lock_payload(versions)
        lock_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[write-lock] {lock_path}")

    if args.check_lock:
        if not lock_path.exists():
            print(f"lock file not found: {lock_path}")
            return 1
        lock_payload = _read_lock(lock_path)
        errors = _compare_lock(versions, lock_payload)
        if errors:
            print("[check-lock] mismatch")
            for item in errors:
                print(f"- {item}")
            return 1
        print("[check-lock] ok")

    _print_summary(versions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
