from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

from report_run import generate_report, resolve_run_package_input

_DELTA_LINE_RE = re.compile(r"^- `([^`]+)` (delta(?: sum)?): `([^`]*)`")


def discover_packages(root: Path) -> list[Path]:
    packages: set[Path] = set()
    for name in ("manifest.json", "run_manifest.json"):
        for manifest in root.rglob(name):
            packages.add(manifest.parent)
    for archive in root.rglob("*.zip"):
        packages.add(archive)
    return sorted(packages, key=lambda item: str(item).lower())


def extract_delta_map(report_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in report_text.splitlines():
        line = raw_line.strip()
        match = _DELTA_LINE_RE.match(line)
        if not match:
            continue
        metric_name = match.group(1)
        delta_kind = match.group(2)
        value = match.group(3)
        values[f"{metric_name} {delta_kind}"] = value
    # explicit count/sum lines not matching generic pattern
    for line in report_text.splitlines():
        line = line.strip()
        if line.startswith("- `byes_e2e_latency_ms_count` delta:"):
            values["byes_e2e_latency_ms_count delta"] = _extract_backtick_value(line)
        elif line.startswith("- `byes_ttfa_ms_count` delta:"):
            values["byes_ttfa_ms_count delta"] = _extract_backtick_value(line)
    return values


def _extract_backtick_value(line: str) -> str:
    parts = re.findall(r"`([^`]*)`", line)
    return parts[-1] if parts else ""


def build_index(
    root: Path,
    out_dir: Path,
    rows: list[dict[str, Any]],
) -> Path:
    index_lines: list[str] = []
    index_lines.append(f"# Run Package Reports - {root}")
    index_lines.append("")
    index_lines.append("| package | scenarioTag | startMs | endMs | frameSent | frame_recv_delta | frame_done_delta | e2e_count_delta | ttfa_count_delta | safemode_delta | throttle_delta | preempt_delta | confirm_req_delta | report |")
    index_lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in rows:
        metrics = row.get("delta", {})
        index_lines.append(
            "| {package} | {scenario} | {start} | {end} | {frame_sent} | {recv} | {done} | {e2e} | {ttfa} | {safe} | {throttle} | {preempt} | {confirm} | `{report}` |".format(
                package=row.get("package", ""),
                scenario=row.get("scenarioTag", ""),
                start=row.get("startMs", ""),
                end=row.get("endMs", ""),
                frame_sent=row.get("frameCountSent", ""),
                recv=metrics.get("byes_frame_received_total delta sum", "n/a"),
                done=metrics.get("byes_frame_completed_total delta sum", "n/a"),
                e2e=metrics.get("byes_e2e_latency_ms_count delta", "n/a"),
                ttfa=metrics.get("byes_ttfa_ms_count delta", "n/a"),
                safe=metrics.get("byes_safemode_enter_total delta sum", "n/a"),
                throttle=metrics.get("byes_throttle_enter_total delta sum", "n/a"),
                preempt=metrics.get("byes_preempt_enter_total delta sum", "n/a"),
                confirm=metrics.get("byes_confirm_request_total delta sum", "n/a"),
                report=row.get("reportPath", ""),
            )
        )

    index_path = out_dir / "index.md"
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return index_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-generate run-package reports")
    parser.add_argument("--root", required=True, help="root directory to scan run packages")
    parser.add_argument("--out", default=None, help="output report directory")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8000/metrics")
    parser.add_argument("--external-readiness-url", default=None)
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists() or not root.is_dir():
        print(f"root not found: {root}")
        return 1

    out_dir = Path(args.out) if args.out else root
    out_dir.mkdir(parents=True, exist_ok=True)

    packages = discover_packages(root)
    if not packages:
        print("no run packages found")
        return 1

    rows: list[dict[str, Any]] = []
    for package in packages:
        cleanup_dir: Path | None = None
        try:
            ws_jsonl, metrics_before, metrics_after, summary, cleanup_dir = resolve_run_package_input(package)
            report_name = f"report_{package.stem if package.is_file() else package.name}.md"
            report_path = out_dir / report_name
            output_path = generate_report(
                ws_jsonl=ws_jsonl,
                output=report_path,
                metrics_url=args.metrics_url,
                metrics_before_path=metrics_before,
                metrics_after_path=metrics_after,
                external_readiness_url=args.external_readiness_url,
                run_package_summary=summary,
            )
            report_text = output_path.read_text(encoding="utf-8")
            rows.append(
                {
                    "package": str(package),
                    "scenarioTag": summary.get("scenarioTag", ""),
                    "startMs": summary.get("startMs", ""),
                    "endMs": summary.get("endMs", ""),
                    "frameCountSent": summary.get("frameCountSent", ""),
                    "reportPath": str(output_path),
                    "delta": extract_delta_map(report_text),
                }
            )
            print(f"generated {output_path}")
        except Exception as ex:
            rows.append(
                {
                    "package": str(package),
                    "scenarioTag": "error",
                    "startMs": "",
                    "endMs": "",
                    "frameCountSent": "",
                    "reportPath": "",
                    "delta": {},
                    "error": str(ex),
                }
            )
            print(f"failed {package}: {ex}")
        finally:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    index_path = build_index(root, out_dir, rows)
    index_json = out_dir / "index.json"
    index_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"index generated -> {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

