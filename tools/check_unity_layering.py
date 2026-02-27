from __future__ import annotations

import re
from pathlib import Path

USING_PATTERN = re.compile(r"^\s*using\s+BYES(?:\.|;)")
SYMBOL_PATTERN = re.compile(r"\bBYES\.")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    root = _repo_root()
    beyour_eyes_root = root / "Assets" / "BeYourEyes"
    if not beyour_eyes_root.exists():
        print("ERROR: Assets/BeYourEyes directory not found.")
        return 1

    violations: list[tuple[Path, int, str]] = []
    for cs_path in sorted(beyour_eyes_root.rglob("*.cs")):
        for line_no, raw_line in enumerate(cs_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            line = raw_line.rstrip()
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if USING_PATTERN.search(line) or SYMBOL_PATTERN.search(line):
                violations.append((cs_path, line_no, stripped))

    if not violations:
        print("Unity layering check passed.")
        return 0

    print("Unity layering check failed. BeYourEyes layer must not depend on BYES namespace:")
    for path, line_no, text in violations:
        rel = path.relative_to(root).as_posix()
        print(f"- {rel}:{line_no}: {text}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
