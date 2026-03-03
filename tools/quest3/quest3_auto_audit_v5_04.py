from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[2]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _http_json(method: str, url: str, *, headers: dict[str, str], body: dict[str, Any] | None = None, timeout: float = 8.0) -> tuple[int, dict[str, Any] | None, str]:
    data: bytes | None = None
    req_headers = dict(headers)
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        data = payload
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, data=data, method=method.upper(), headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            if isinstance(parsed, dict):
                return int(resp.status), parsed, ""
            return int(resp.status), {"value": parsed}, ""
    except urllib.error.HTTPError as exc:
        try:
            payload_text = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(payload_text) if payload_text.strip() else None
        except Exception:
            parsed = None
        detail = ""
        if isinstance(parsed, dict):
            detail = str(parsed.get("detail", "")).strip()
        if not detail:
            detail = f"http_{exc.code}"
        return int(exc.code), parsed if isinstance(parsed, dict) else None, detail
    except Exception as exc:  # noqa: BLE001
        return 0, None, f"request_failed:{exc.__class__.__name__}:{exc}"


def _run_cmd(cmd: list[str], *, cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)  # noqa: S603
    return int(proc.returncode), proc.stdout, proc.stderr


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Quest v5.04 automation: capabilities + record -> replay -> report")
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--device-id", default="quest3-smoke")
    parser.add_argument("--record-sec", type=float, default=4.0)
    parser.add_argument("--gateway-api-key", default=os.getenv("BYES_GATEWAY_API_KEY", ""))
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "Gateway" / "artifacts" / "quest_audit"))
    parser.add_argument("--skip-replay", action="store_true")
    parser.add_argument("--skip-report", action="store_true")
    args = parser.parse_args()

    base_url = str(args.base_url).rstrip("/")
    device_id = str(args.device_id).strip() or "quest3-smoke"
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    headers: dict[str, str] = {"Accept": "application/json"}
    api_key = str(args.gateway_api_key or "").strip()
    if api_key:
        headers["X-BYES-API-Key"] = api_key

    summary: dict[str, Any] = {
        "startedAt": _now_utc_iso(),
        "baseUrl": base_url,
        "deviceId": device_id,
        "steps": {},
    }

    def step(name: str, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any] | None]:
        url = base_url + path
        code, data, err = _http_json(method, url, headers=headers, body=body)
        ok = 200 <= code < 300
        summary["steps"][name] = {
            "method": method.upper(),
            "path": path,
            "status": code,
            "ok": ok,
            "error": err,
            "data": data,
        }
        return ok, data

    ok_version, version_data = step("version", "GET", "/api/version")
    ok_health, health_data = step("health", "GET", "/api/health")
    ok_cap, cap_data = step("capabilities", "GET", "/api/capabilities")

    if not (ok_version and ok_health and ok_cap):
        summary["result"] = "fail"
        summary["reason"] = "gateway_probe_failed"
        json_path = out_dir / "quest_v504_audit_summary.json"
        _write_text(json_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(f"[quest_v504_audit] failed: gateway probe failed; see {json_path}")
        return 2

    ok_start, start_data = step(
        "record_start",
        "POST",
        "/api/record/start",
        {
            "deviceId": device_id,
            "note": "quest_v5_04_auto_audit",
            "maxSec": max(5, int(round(float(args.record_sec) + 2))),
            "maxFrames": 0,
        },
    )
    if not ok_start:
        summary["result"] = "fail"
        summary["reason"] = "record_start_failed"
        json_path = out_dir / "quest_v504_audit_summary.json"
        _write_text(json_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(f"[quest_v504_audit] failed: record_start; see {json_path}")
        return 3

    sleep_sec = max(1.0, float(args.record_sec))
    print(f"[quest_v504_audit] recording for {sleep_sec:.1f}s... (operate in Quest now if connected)")
    time.sleep(sleep_sec)

    ok_stop, stop_data = step(
        "record_stop",
        "POST",
        "/api/record/stop",
        {
            "deviceId": device_id,
        },
    )
    if not ok_stop:
        summary["result"] = "fail"
        summary["reason"] = "record_stop_failed"
        json_path = out_dir / "quest_v504_audit_summary.json"
        _write_text(json_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(f"[quest_v504_audit] failed: record_stop; see {json_path}")
        return 4

    recording_path = ""
    if isinstance(stop_data, dict):
        recording_path = str(stop_data.get("recordingPath", "")).strip()
    if not recording_path:
        summary["result"] = "fail"
        summary["reason"] = "recording_path_missing"
        json_path = out_dir / "quest_v504_audit_summary.json"
        _write_text(json_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(f"[quest_v504_audit] failed: recordingPath missing; see {json_path}")
        return 5

    run_package = Path(recording_path)
    if not run_package.is_absolute():
        run_package = (REPO_ROOT / run_package).resolve()
    summary["recordingPath"] = str(run_package)

    if not args.skip_replay:
        replay_cmd = [
            sys.executable,
            str(REPO_ROOT / "Gateway" / "scripts" / "replay_run_package.py"),
            "--run-package",
            str(run_package),
            "--base-url",
            base_url,
            "--reset",
        ]
        if api_key:
            replay_cmd.extend(["--gateway-api-key", api_key])
        rc, out, err = _run_cmd(replay_cmd, cwd=REPO_ROOT)
        summary["steps"]["replay"] = {
            "cmd": replay_cmd,
            "rc": rc,
            "stdoutTail": "\n".join(out.splitlines()[-40:]),
            "stderrTail": "\n".join(err.splitlines()[-40:]),
            "ok": rc == 0,
        }
        if rc != 0:
            summary["result"] = "fail"
            summary["reason"] = "replay_failed"
            json_path = out_dir / "quest_v504_audit_summary.json"
            _write_text(json_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
            print(f"[quest_v504_audit] failed: replay; see {json_path}")
            return 6

    report_md = out_dir / "quest_v504_report.md"
    report_json = out_dir / "quest_v504_report.json"
    if not args.skip_report:
        report_cmd = [
            sys.executable,
            str(REPO_ROOT / "Gateway" / "scripts" / "report_run.py"),
            "--run-package",
            str(run_package),
            "--output",
            str(report_md),
            "--output-json",
            str(report_json),
        ]
        rc, out, err = _run_cmd(report_cmd, cwd=REPO_ROOT)
        summary["steps"]["report"] = {
            "cmd": report_cmd,
            "rc": rc,
            "stdoutTail": "\n".join(out.splitlines()[-40:]),
            "stderrTail": "\n".join(err.splitlines()[-40:]),
            "ok": rc == 0,
        }
        if rc != 0:
            summary["result"] = "fail"
            summary["reason"] = "report_failed"
            json_path = out_dir / "quest_v504_audit_summary.json"
            _write_text(json_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
            print(f"[quest_v504_audit] failed: report; see {json_path}")
            return 7

    summary["result"] = "ok"
    summary["finishedAt"] = _now_utc_iso()
    summary_path = out_dir / "quest_v504_audit_summary.json"
    _write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")

    lines: list[str] = []
    lines.append("# Quest v5.04 Auto Audit")
    lines.append("")
    lines.append(f"- started: {summary.get('startedAt', '-')}")
    lines.append(f"- finished: {summary.get('finishedAt', '-')}")
    lines.append(f"- baseUrl: {base_url}")
    lines.append(f"- deviceId: {device_id}")
    lines.append(f"- recordingPath: {summary.get('recordingPath', '-')}")
    lines.append(f"- report: {report_md if report_md.exists() else '-'}")
    lines.append("")
    lines.append("## Capabilities")
    providers = {}
    if isinstance(cap_data, dict):
        providers = cap_data.get("available_providers") or {}
    if isinstance(providers, dict):
        for key in sorted(providers.keys()):
            value = providers.get(key)
            if isinstance(value, dict):
                lines.append(f"- {key}: enabled={value.get('enabled')} backend={value.get('backend')} reason={value.get('reason')}")
            else:
                lines.append(f"- {key}: {value}")
    md_path = out_dir / "quest_v504_audit_summary.md"
    _write_text(md_path, "\n".join(lines) + "\n")

    print("[quest_v504_audit] OK")
    print(f"  summary json: {summary_path}")
    print(f"  summary md  : {md_path}")
    if report_md.exists():
        print(f"  report md   : {report_md}")
    if report_json.exists():
        print(f"  report json : {report_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
