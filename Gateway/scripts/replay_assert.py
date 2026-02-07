from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def count_risk(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("event", {}).get("type") == "risk")


def count_safemode(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        event = row.get("event", {})
        if event.get("type") != "health":
            continue
        summary = str(event.get("summary", ""))
        if "gateway_safe_mode" in summary:
            count += 1
    return count


def count_expired(rows: list[dict[str, Any]]) -> int:
    expired = 0
    for row in rows:
        event = row.get("event", {})
        ts = event.get("timestampMs")
        ttl = event.get("ttlMs")
        recv = row.get("receivedAtMs")
        if not isinstance(ts, int) or not isinstance(ttl, int) or not isinstance(recv, int):
            continue
        if ttl <= 0:
            expired += 1
            continue
        if recv - ts > ttl:
            expired += 1
    return expired


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two WS jsonl recordings")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()

    baseline = load_jsonl(Path(args.baseline))
    candidate = load_jsonl(Path(args.candidate))

    base_risk = count_risk(baseline)
    cand_risk = count_risk(candidate)
    base_safe = count_safemode(baseline)
    cand_safe = count_safemode(candidate)
    base_expired = count_expired(baseline)
    cand_expired = count_expired(candidate)

    print(f"baseline risk={base_risk} safeMode={base_safe} expired={base_expired}")
    print(f"candidate risk={cand_risk} safeMode={cand_safe} expired={cand_expired}")

    ok = True
    if base_risk != cand_risk:
        print("FAIL: risk count mismatch")
        ok = False
    if base_safe != cand_safe:
        print("FAIL: safe mode enter count mismatch")
        ok = False
    if cand_expired > 0:
        print("FAIL: candidate has expired-emitted events")
        ok = False

    if ok:
        print("PASS: replay assertions matched")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
