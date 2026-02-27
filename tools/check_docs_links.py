from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

LINK_RE = re.compile(r"!?[^\[]*\[[^\]]+\]\(([^)]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "tel:")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _markdown_files(root: Path) -> list[Path]:
    files = [root / "README.md"]
    files.extend(sorted((root / "docs").rglob("*.md")))
    return [path for path in files if path.exists()]


def _normalize_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    return target


def _resolve_relative_target(source_file: Path, target: str, repo_root: Path) -> Path | None:
    cleaned = unquote(target.split("#", 1)[0].split("?", 1)[0]).strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace("\\", "/")
    if cleaned.startswith("/"):
        return (repo_root / cleaned.lstrip("/")).resolve()
    return (source_file.parent / cleaned).resolve()


def _is_skipped_target(target: str) -> bool:
    lowered = target.lower()
    if not lowered or lowered.startswith("#"):
        return True
    if lowered.startswith(SKIP_PREFIXES):
        return True
    return False


def main() -> int:
    repo_root = _repo_root()
    missing: list[tuple[Path, int, str, Path]] = []

    for markdown_file in _markdown_files(repo_root):
        in_code_fence = False
        for line_no, raw_line in enumerate(markdown_file.read_text(encoding="utf-8-sig").splitlines(), start=1):
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_code_fence = not in_code_fence
                continue
            if in_code_fence:
                continue

            for match in LINK_RE.finditer(raw_line):
                target = _normalize_target(match.group(1))
                if _is_skipped_target(target):
                    continue
                resolved = _resolve_relative_target(markdown_file, target, repo_root)
                if resolved is None:
                    continue
                if not resolved.exists():
                    missing.append((markdown_file, line_no, target, resolved))

    if not missing:
        print("Docs relative link check passed.")
        return 0

    print("Docs relative link check failed. Missing targets:")
    for source, line_no, target, resolved in missing:
        rel_source = source.relative_to(repo_root).as_posix()
        rel_resolved = (
            resolved.relative_to(repo_root).as_posix()
            if resolved.is_relative_to(repo_root)
            else str(resolved)
        )
        print(f"- {rel_source}:{line_no} -> {target} (resolved: {rel_resolved})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
