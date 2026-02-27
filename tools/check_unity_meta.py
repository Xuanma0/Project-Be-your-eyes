from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_allowlist(root: Path) -> set[str]:
    allowlist_path = root / "tools" / "unity_meta_allowlist.txt"
    if not allowlist_path.exists():
        return set()
    entries: set[str] = set()
    for raw in allowlist_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line.replace("\\", "/").strip())
    return entries


def _iter_asset_paths(assets_root: Path):
    for path in assets_root.rglob("*"):
        if path.name.endswith(".meta"):
            continue
        yield path


def main() -> int:
    root = _repo_root()
    assets_root = root / "Assets"
    if not assets_root.exists():
        print("ERROR: Assets/ directory not found")
        return 1

    allowlist = _load_allowlist(root)
    missing: list[Path] = []
    for path in _iter_asset_paths(assets_root):
        meta_path = path.with_name(f"{path.name}.meta")
        if not meta_path.exists():
            missing.append(path)

    if not missing:
        print("Unity meta completeness check passed.")
        return 0

    missing_rel = [path.relative_to(root).as_posix() for path in missing]
    unknown_missing = [path for path in missing_rel if path not in allowlist]

    if not unknown_missing:
        print(
            "Unity meta completeness check passed (no new missing .meta; "
            f"allowlisted gaps: {len(missing_rel)})."
        )
        return 0

    print("Unity meta completeness check failed. Missing .meta for:")
    for rel in sorted(unknown_missing):
        print(f"- {rel}")
    print(
        "\nIf these are intentional legacy gaps, add them to tools/unity_meta_allowlist.txt "
        "with one relative path per line."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
