from __future__ import annotations

import argparse
import re
from pathlib import Path

SUCCESS_MARKERS = (
    "Build completed with a result of 'Succeeded'",
    "Build Finished, Result: Success.",
    "[ByesBuildQuest3] Result=Succeeded",
)
ERROR_PATTERNS = [
    re.compile(r"error\s+CS\d+", re.IGNORECASE),
    re.compile(r"fatal error:", re.IGNORECASE),
    re.compile(r"\berror:\b", re.IGNORECASE),
    re.compile(r"ld\.lld:", re.IGNORECASE),
    re.compile(r"undefined symbol", re.IGNORECASE),
    re.compile(r"undefined reference", re.IGNORECASE),
    re.compile(r"BuildFailedException", re.IGNORECASE),
    re.compile(r"Switching to AndroidPlayer is disabled", re.IGNORECASE),
    re.compile(r"Android build target is not supported", re.IGNORECASE),
]
BEE_ANDROID_PATTERN = re.compile(r"Building\s+Library\\Bee\\artifacts\\Android", re.IGNORECASE)
FAILED_PATTERN = re.compile(r"failed", re.IGNORECASE)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _find_first_error_line(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        for pattern in ERROR_PATTERNS:
            if pattern.search(line):
                return index
    return None


def _count_bee_android_failures(lines: list[str]) -> tuple[int, int]:
    total_hits = 0
    failed_hits = 0
    for line in lines:
        if BEE_ANDROID_PATTERN.search(line):
            total_hits += 1
            if FAILED_PATTERN.search(line):
                failed_hits += 1
    return total_hits, failed_hits


def _render_context(lines: list[str], error_index: int, context_size: int = 80) -> str:
    start = max(0, error_index - context_size)
    end = min(len(lines), error_index + context_size + 1)
    rendered: list[str] = []
    for line_no in range(start, end):
        prefix = "=>" if line_no == error_index else "  "
        rendered.append(f"{prefix} {line_no + 1:05d}: {lines[line_no]}")
    return "\n".join(rendered)


def _write_summary(summary_path: Path, content: str) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Unity Android build log and extract root cause.")
    parser.add_argument("log_path", type=Path)
    args = parser.parse_args()

    repo_root = _repo_root()
    summary_path = repo_root / "Builds" / "logs" / "unity_build_quest3_android_v4.99.summary.txt"

    if not args.log_path.exists():
        _write_summary(
            summary_path,
            "[parse] Build failed and log file was not found.\n"
            f"log_path={args.log_path}\n"
            "Open Unity Editor.log for details.",
        )
        return 2

    lines = args.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    bee_total, bee_failed = _count_bee_android_failures(lines)
    succeeded = any(any(marker in line for marker in SUCCESS_MARKERS) for line in lines)
    first_error = _find_first_error_line(lines)

    report_lines: list[str] = [
        f"log_path={args.log_path}",
        f"summary_path={summary_path}",
        f"bee_android_hits={bee_total}",
        f"bee_android_failed_hits={bee_failed}",
        f"detected_success={succeeded}",
    ]

    if succeeded:
        report_lines.append("status=SUCCEEDED")
        _write_summary(summary_path, "\n".join(report_lines) + "\n")
        return 0

    if first_error is not None:
        report_lines.append("status=FAILED")
        report_lines.append(f"first_error_line={first_error + 1}")
        report_lines.append("--- root cause context (+/-80 lines) ---")
        report_lines.append(_render_context(lines, first_error))
        _write_summary(summary_path, "\n".join(report_lines) + "\n")
        return 1

    report_lines.append("status=FAILED")
    report_lines.append("root_cause=NOT_FOUND")
    report_lines.append("Open Unity Editor.log for full diagnostics.")
    _write_summary(summary_path, "\n".join(report_lines) + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
