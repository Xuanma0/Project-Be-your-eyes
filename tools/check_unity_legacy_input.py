from __future__ import annotations

import re
from pathlib import Path

LEGACY_EXPR_TOKEN = "ENABLE_LEGACY_INPUT_MANAGER"
LEGACY_API_PATTERNS = [
    re.compile(r"\bInput\.(?:GetKey|GetKeyDown|GetKeyUp|GetAxis|GetButton|GetMouseButton|mousePosition|touchCount)\b"),
    re.compile(r"UnityEngine\.Input(?!System)"),
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _expr_allows_legacy(expr: str) -> bool:
    normalized = expr.replace(" ", "")
    if LEGACY_EXPR_TOKEN not in normalized:
        return False
    if f"!{LEGACY_EXPR_TOKEN}" in normalized:
        return False
    return True


def main() -> int:
    root = _repo_root()
    assets_root = root / "Assets"
    if not assets_root.exists():
        print("ERROR: Assets/ directory not found")
        return 1

    violations: list[tuple[Path, int, str]] = []
    for cs_path in sorted(assets_root.rglob("*.cs")):
        guard_stack: list[bool] = []
        lines = cs_path.read_text(encoding="utf-8-sig").splitlines()
        for line_no, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            if stripped.startswith("#if"):
                guard_stack.append(_expr_allows_legacy(stripped[3:].strip()))
                continue
            if stripped.startswith("#elif"):
                if guard_stack:
                    guard_stack[-1] = _expr_allows_legacy(stripped[5:].strip())
                continue
            if stripped.startswith("#else"):
                if guard_stack:
                    guard_stack[-1] = False
                continue
            if stripped.startswith("#endif"):
                if guard_stack:
                    guard_stack.pop()
                continue

            if stripped.startswith("//"):
                continue

            has_legacy_api = any(pattern.search(raw_line) for pattern in LEGACY_API_PATTERNS)
            if not has_legacy_api:
                continue

            if any(guard_stack):
                continue

            rel = cs_path.relative_to(root)
            violations.append((rel, line_no, stripped))

    if not violations:
        print("Unity legacy input guard passed.")
        return 0

    print("Unity legacy input guard failed. Legacy Input API must be wrapped with #if ENABLE_LEGACY_INPUT_MANAGER.")
    for rel, line_no, text in violations:
        print(f"- {rel.as_posix()}:{line_no}: {text}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
